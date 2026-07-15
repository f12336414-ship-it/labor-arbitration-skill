"""Stable machine- and human-readable validation finding records."""

from __future__ import annotations


GUIDANCE = {
    "CASE_WORKSPACE_OBJECT_HASH_MISMATCH": (
        "案件工作区对象字节与清单哈希不一致，工作区可能损坏或被修改。",
        "Stop using this workspace and rebuild a new workspace from sources or a controlled backup that still matches the intake manifest.",
    ),
    "LEGAL_FRESHNESS_DERIVATION_MISMATCH": (
        "法律来源新鲜度状态与绑定的前后正文哈希或时间不一致。",
        "Regenerate the freshness record from the bound frozen observations and keep the output in DRAFT.",
    ),
    "LEGAL_TEXT_DIFF_SNAPSHOT_MISMATCH": (
        "法律文本差异记录已变化，但 RFC 8785 快照没有同步更新。",
        "Regenerate the complete exact diff from both bound UTF-8 source texts; do not hand-edit or truncate it.",
    ),
    "LEGAL_VERSION_GRAPH_SNAPSHOT_MISMATCH": (
        "法律版本图已变化，但版本图快照没有同步更新。",
        "Recalculate the graph snapshot and invalidate every downstream freshness, selection, analysis, calculation, and document binding.",
    ),
    "OFFICIAL_CASE_SNAPSHOT_MISMATCH": (
        "官方公开案例分类记录已变化，但案例记录快照没有同步更新。",
        "Rebuild the classification from the frozen OFFICIAL_CASE record and retain the privacy and redistribution blocks.",
    ),
    "OUTPUT_LEGAL_FRESHNESS_DRAFT_ONLY": (
        "法律来源检查缺失、不可用、陈旧或已变化，输出只能保持草稿。",
        "Keep or downgrade the artifact to DRAFT, obtain a new frozen observation, and bind a newly validated freshness snapshot.",
    ),
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
    "OUTPUT_INVALIDATION_DECLARATION_MISMATCH": (
        "输出失效声明与前后依赖摘要不一致，旧状态不能继续复用。",
        "Declare the exact dependency changes and downgrade the output before revalidation.",
    ),
    "OUTPUT_PREVIOUS_BINDING_MISMATCH": (
        "前一状态绑定不属于同一输出对象或类型，不能用来证明本次转换。",
        "Bind the previous state to the same artifact_id and artifact_type, then regenerate the request snapshot.",
    ),
    "OUTPUT_REVIEW_REQUIRED_UNSUPPORTED": (
        "当前版本尚不能验证进入 REVIEW_REQUIRED 所需的法律来源、分析和专业计算前置条件。",
        "Keep the artifact in DRAFT until the required legal-source, analysis, and calculator gates are implemented.",
    ),
    "OUTPUT_STATE_REQUEST_SNAPSHOT_MISMATCH": (
        "输出状态请求已变化，但 RFC 8785 请求摘要没有同步更新。",
        "Recalculate state_request_sha256 from the complete current request.",
    ),
    "OUTPUT_STATE_REVALIDATION_REQUIRED": (
        "案件、法律、分析、计算或文书依赖已变化，必须降级并重新验证。",
        "Downgrade to DRAFT or INTERNAL_ANALYSIS and revalidate every changed dependency.",
    ),
    "OUTPUT_STATE_TRANSITION_INVALID": (
        "输出状态转换跳过了必要技术阶段或使用了不支持的路径。",
        "Start at INTERNAL_ANALYSIS and use only the published transition sequence.",
    ),
    "REVIEW_PACKET_REFERENCE_UNKNOWN": (
        "审查包引用了包内不存在的来源、问题或对象标识。",
        "Correct the reference to an identifier declared in the same packet, then regenerate dependent snapshots.",
    ),
    "REVIEW_PACKET_RULE_DEPENDENCY_MISMATCH": (
        "请求权或计算器的规则引用没有逐一绑定规则审查包版本。",
        "Declare exactly one rule dependency for every rule_id, including the rule packet ID and both RFC 8785 snapshots.",
    ),
    "REVIEW_PACKET_SCHEMA_VALIDATION_ERROR": (
        "审查包结构不符合发布的 v1.0 契约，不能进入交叉验证。",
        "Correct the packet against references/review-packet.schema.json; do not add approval fields or weaken the schema.",
    ),
    "REVIEW_PACKET_SNAPSHOT_MISMATCH": (
        "完整审查包已变化，但包快照没有按 RFC 8785 同步更新。",
        "Recalculate packet_snapshot_sha256 after every status or review-record change.",
    ),
    "REVIEW_PACKET_STATUS_INVALID": (
        "审查包状态与已有审核意见不一致，不能按该状态继续。",
        "Use a status whose prerequisites match the review records; agreement never grants legal approval.",
    ),
    "REVIEW_SUBJECT_SNAPSHOT_MISMATCH": (
        "规则、请求权或计算器审核对象已变化，旧的对象摘要和审核意见不能复用。",
        "Recalculate review_subject_sha256 and obtain new cross-validation responses for the changed subject.",
    ),
    "REVIEW_QUESTION_SUBJECT_PATH_UNKNOWN": (
        "审核问题指向的对象字段不存在，无法证明该字段已经被逐项审核。",
        "Point subject_paths to fields that exist in the current subject, then regenerate snapshots and review responses.",
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
