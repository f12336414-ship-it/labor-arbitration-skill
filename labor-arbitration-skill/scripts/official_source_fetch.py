"""Narrow HTTPS transport for one reviewed official-source candidate document."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import math
import ssl
from urllib.parse import urljoin

from source_fetch_policy import FetchRefusal, FetchedSource, validate_fetch_target


MAX_REDIRECTS = 3
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
CAPTURED_HEADERS = {
    "content_type": "Content-Type",
    "content_length": "Content-Length",
    "date": "Date",
    "etag": "ETag",
    "last_modified": "Last-Modified",
}


def _public_peer_ip(connection) -> str:
    if connection.sock is None:
        raise FetchRefusal("FETCH_TLS_CONNECTION_MISSING", "TLS socket was not established.")
    peer_ip = connection.sock.getpeername()[0]
    try:
        address = ipaddress.ip_address(peer_ip)
    except ValueError as error:
        raise FetchRefusal("FETCH_PEER_IP_INVALID", "TLS peer IP is invalid.") from error
    if not address.is_global:
        raise FetchRefusal(
            "FETCH_PRIVATE_NETWORK_REFUSED",
            "Official-source fetching refuses non-global peer addresses.",
        )
    return address.compressed


def _tls_metadata(connection) -> tuple[str, str, str]:
    tls_version = connection.sock.version()
    cipher = connection.sock.cipher()
    certificate = connection.sock.getpeercert(binary_form=True)
    if tls_version not in {"TLSv1.2", "TLSv1.3"} or not cipher or not certificate:
        raise FetchRefusal(
            "FETCH_TLS_POLICY_REFUSED",
            "TLS 1.2 or newer with a peer certificate and negotiated cipher is required.",
        )
    return tls_version, cipher[0], hashlib.sha256(certificate).hexdigest()


def _default_connection_factory(host: str, timeout_seconds: float):
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return http.client.HTTPSConnection(
        host,
        port=443,
        timeout=timeout_seconds,
        context=context,
    )


def fetch_official_source(
    url: str,
    publisher_code: str,
    purpose: str,
    *,
    timeout_seconds: float = 20.0,
    max_response_bytes: int | None = None,
    connection_factory=None,
) -> FetchedSource:
    if (
        not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or timeout_seconds > 60
    ):
        raise FetchRefusal("FETCH_TIMEOUT_INVALID", "Timeout must be greater than 0 and at most 60 seconds.")
    entry, _parsed, _host, _path = validate_fetch_target(url, publisher_code, purpose)
    registry_maximum = entry["max_response_bytes"]
    byte_limit = registry_maximum if max_response_bytes is None else max_response_bytes
    if byte_limit < 1 or byte_limit > registry_maximum:
        raise FetchRefusal(
            "FETCH_SIZE_LIMIT_INVALID",
            "Response byte limit must be positive and no greater than the publisher registry limit.",
        )
    factory = connection_factory or _default_connection_factory
    current_url = url
    hops = []

    for redirect_index in range(MAX_REDIRECTS + 1):
        entry, _parsed, host, request_target = validate_fetch_target(
            current_url, publisher_code, purpose
        )
        connection = factory(host, timeout_seconds)
        try:
            connection.connect()
            peer_ip = _public_peer_ip(connection)
            tls_version, tls_cipher, certificate_sha256 = _tls_metadata(connection)
            connection.request(
                "GET",
                request_target,
                headers={
                    "Accept": ", ".join(entry["allowed_media_types"]),
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                    "User-Agent": "LaborBalanceOfficialSourceFetcher/1.0",
                },
            )
            response = connection.getresponse()
            location = response.getheader("Location")
            redirect_location = (
                urljoin(current_url, location) if location is not None else None
            )
            hop = {
                "url": current_url,
                "status": response.status,
                "peer_ip": peer_ip,
                "tls_version": tls_version,
                "tls_cipher": tls_cipher,
                "peer_certificate_sha256": certificate_sha256,
                "redirect_location": redirect_location,
            }
            hops.append(hop)

            if response.status in REDIRECT_STATUSES:
                if redirect_location is None:
                    raise FetchRefusal(
                        "FETCH_REDIRECT_LOCATION_MISSING",
                        "Redirect response did not include a Location header.",
                    )
                if redirect_index >= MAX_REDIRECTS:
                    raise FetchRefusal(
                        "FETCH_REDIRECT_LIMIT_EXCEEDED",
                        "Official-source redirect count exceeded the hard limit.",
                    )
                validate_fetch_target(redirect_location, publisher_code, purpose)
                current_url = redirect_location
                continue

            if response.status != 200:
                raise FetchRefusal(
                    "FETCH_HTTP_STATUS_REFUSED",
                    f"Official-source response status {response.status} is not accepted.",
                )
            content_encoding = response.getheader("Content-Encoding")
            if content_encoding not in {None, "", "identity"}:
                raise FetchRefusal(
                    "FETCH_CONTENT_ENCODING_REFUSED",
                    "Compressed or transformed response bodies are refused; request exact identity bytes.",
                )
            content_type = response.getheader("Content-Type")
            if not content_type:
                raise FetchRefusal(
                    "FETCH_MEDIA_TYPE_MISSING", "Response Content-Type is required."
                )
            media_type = content_type.split(";", 1)[0].strip().lower()
            if media_type not in entry["allowed_media_types"]:
                raise FetchRefusal(
                    "FETCH_MEDIA_TYPE_REFUSED",
                    f"Response media type {media_type} is not allowed for the publisher.",
                )
            declared_length = response.getheader("Content-Length")
            if declared_length is not None:
                try:
                    declared_length_value = int(declared_length)
                except ValueError as error:
                    raise FetchRefusal(
                        "FETCH_CONTENT_LENGTH_INVALID",
                        "Response Content-Length must be a non-negative integer.",
                    ) from error
                if declared_length_value < 0 or declared_length_value > byte_limit:
                    raise FetchRefusal(
                        "FETCH_RESPONSE_TOO_LARGE",
                        "Response Content-Length exceeds the configured limit.",
                    )

            body = bytearray()
            while True:
                chunk = response.read(min(65536, byte_limit + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > byte_limit:
                    raise FetchRefusal(
                        "FETCH_RESPONSE_TOO_LARGE",
                        "Response body exceeded the configured limit.",
                    )
            if declared_length is not None and len(body) != declared_length_value:
                raise FetchRefusal(
                    "FETCH_CONTENT_LENGTH_MISMATCH",
                    "Response body size does not match the declared Content-Length.",
                )
            response_headers = {
                field: response.getheader(header)
                for field, header in CAPTURED_HEADERS.items()
            }
            if any(
                value is not None and len(value) > 1000
                for value in response_headers.values()
            ):
                raise FetchRefusal(
                    "FETCH_RESPONSE_HEADER_TOO_LARGE",
                    "A captured response header exceeds the storage contract.",
                )
            return FetchedSource(
                body=bytes(body),
                final_url=current_url,
                media_type=media_type,
                network_hops=hops,
                response_headers=response_headers,
                status=response.status,
            )
        finally:
            connection.close()

    raise FetchRefusal("FETCH_REDIRECT_LIMIT_EXCEEDED", "Redirect limit exceeded.")
