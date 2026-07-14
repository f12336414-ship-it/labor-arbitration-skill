"""Stable machine- and human-readable validation finding records."""

from __future__ import annotations


GUIDANCE = {
    "DATE_FORMAT_INVALID": (
        "日期格式或日历日期无效。请使用真实存在的 ISO 日期；时间戳须为以 Z 结尾的 UTC RFC 3339。",
        "Replace the value with a real ISO calendar date or UTC RFC 3339 timestamp, then regenerate dependent snapshots.",
    ),
    "INTAKE_MANIFEST_SELF_HASH_MISMATCH": (
        "材料清单自哈希与内容不一致，清单可能被修改或生成不完整。",
        "Regenerate the manifest from the original input tree; do not hand-edit its self-hash.",
    ),
    "PACKAGE_SNAPSHOT_MISMATCH": (
        "案件包内容或请求状态已变化，但包快照没有同步更新。",
        "Recalculate the RFC 8785 package snapshot from the complete current package.",
    ),
    "SOURCE_HASH_STATUS_INVALID": (
        "当前版本没有认证抓取链，来源哈希状态只能保持“声明但未验证”。",
        "Set content_hash_status to DECLARED_UNVERIFIED or use a future authenticated fetch workflow outside v0.3.",
    ),
    "SOURCE_HOST_NOT_ALLOWLISTED": (
        "来源 URL 与声明发布者的候选官方主机不匹配。主机匹配本身也不证明法律效力。",
        "Correct the publisher code or use an exact reviewed HTTPS candidate host; independently verify the legal source.",
    ),
    "STATE_REQUEST_MISMATCH": (
        "请求的技术状态没有绑定当前案件包与依赖快照。",
        "Recalculate package_snapshot_sha256 first, then regenerate state_request_sha256.",
    ),
}


def finding(code: str, path: str, message: str, severity: str = "P1") -> dict:
    message_zh, remediation = GUIDANCE.get(
        code,
        (
            "校验未通过；请按 code、path 和 message 修正数据后重新运行。",
            "Correct the value at path, regenerate all dependent RFC 8785 snapshots, and rerun validation.",
        ),
    )
    return {
        "code": code,
        "message": message,
        "message_zh": message_zh,
        "path": path,
        "remediation": remediation,
        "severity": severity,
    }


def format_schema_path(path_parts) -> str:
    path = "$"
    for part in path_parts:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path
