"""Network-free policy and data model for official-source fetching."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from source_registry import registry_entry


FETCHER_NAME = "LaborBalanceOfficialSourceFetcher"
FETCHER_VERSION = "1.0.0"


class FetchRefusal(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FetchedSource:
    body: bytes
    final_url: str
    media_type: str
    network_hops: list[dict]
    response_headers: dict[str, str | None]
    status: int


def validate_fetch_target(url: str, publisher_code: str, purpose: str):
    entry = registry_entry(publisher_code)
    if entry is None:
        raise FetchRefusal("FETCH_PUBLISHER_NOT_REGISTERED", "Publisher is not registered.")
    if purpose not in entry["permitted_purposes"]:
        raise FetchRefusal(
            "FETCH_PURPOSE_NOT_PERMITTED",
            "The registry does not permit this source purpose for the publisher.",
        )
    if not isinstance(url, str) or len(url) > 2048:
        raise FetchRefusal("FETCH_URL_INVALID", "URL must be a bounded HTTPS string.")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise FetchRefusal("FETCH_URL_INVALID", "URL cannot be parsed safely.") from error
    host = parsed.hostname.lower() if parsed.hostname else None
    if (
        parsed.scheme.lower() != "https"
        or host not in entry["hosts"]
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.fragment
    ):
        raise FetchRefusal(
            "FETCH_TARGET_NOT_ALLOWLISTED",
            "Every request and redirect must use an exact reviewed HTTPS host without credentials, fragments, or non-standard ports.",
        )
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    if parsed.query:
        path += "?" + quote(parsed.query, safe="=&;%:@!$'()*+,-._~/?")
    return entry, parsed, host, path
