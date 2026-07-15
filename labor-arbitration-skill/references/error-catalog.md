# 错误处理指南

验证报告中的每条 finding 都包含稳定 `code`、字段 `path`、英文 `message`、中文 `message_zh`、`remediation` 和严重级别。修复输入后必须重新生成所有受影响的 RFC 8785 摘要，不能编辑报告来消除错误。

| 错误族 | 含义 | 处理 |
| --- | --- | --- |
| `SCAN_*_LIMIT_EXCEEDED` | 文件数、单文件、总量、深度或时间超过边界 | 缩小明确授权的输入范围，或在风险评估后显式调整对应 CLI 上限；不要删除安全检查 |
| `SCAN_*_CHANGED_DURING_READ` | 文件或整棵目录在扫描窗口内变化 | 停止写入、同步或杀毒修改，确认目录稳定后重新扫描 |
| `SCAN_REPARSE_POINT_REFUSED` / `SCAN_MOUNT_POINT_REFUSED` | 输入可能越过授权目录 | 复制所需普通文件到隔离目录，不要让 scanner 跟随链接 |
| `PARSER_WORKER_TIMEOUT` / `PARSER_WORKER_*` | 隔离子进程超时、协议、输出或启动失败 | 保留原件，检查资源限制和运行时，不得改写结果绕过边界 |
| `PARSER_ARCHIVE_*` / `PARSER_XML_*` | 压缩包路径、体积、压缩比、链接、加密或 XML 主动声明不安全 | 在独立受控环境转换为简单格式后重新登记原始字节与转换结果 |
| `PARSER_OOXML_*` | Office 文件含宏、外链、嵌入对象或无效关系 | 删除主动内容需由用户在副本中明确完成；原件必须保留且不得执行 |
| `PARSER_PDF_ADAPTER_NOT_IMPLEMENTED` / `PARSER_IMAGE_OCR_NOT_IMPLEMENTED` | 当前隔离等级未批准 PDF/OCR 引擎 | 保持拒绝，等待 P6-03 沙箱和受审引擎，不得把二进制当作文本 |
| `FACT_ANCHOR_*` / `FACT_PARSE_BINDING_MISMATCH` | 事实候选无法对绑定的解析记录、原始对象、坐标或文本哈希重放 | 保留原记录，重新解析原始对象并创建新候选；不得手改锚点或沿用旧确认 |
| `FACT_PREVIOUS_RECORD_*` / `FACT_TRANSITION_*` | 人工标注或失效修订缺少准确前序快照、时间回退或状态转换不合法 | 提供未改动的直接前序记录；从活动 `EXTRACTED` 记录重新派生，不得原地改状态 |
| `FACT_STATE_*` / `FACT_EXACT_*` / `FACT_ADJUDICATIVE_*` | 来源状态、人员自声明、原文或裁判类文书上下文不一致 | 保持候选为未验证；逐字重放原锚点并重新记录自声明，禁止解释为事实真值或裁判认证 |
| `FACT_ID_*` / `FACT_SNAPSHOT_*` / `FACT_ASSERTION_*` | 候选 ID、RFC 8785 快照或陈述文本摘要失效 | 从有效解析记录与前序记录重建新修订；不得覆盖原历史记录 |
| `INTAKE_MANIFEST_*` | manifest Schema、自哈希或案件包绑定失败 | 从原始目录重新生成 manifest，并按顺序重算 intake/package/state 摘要 |
| `SOURCE_HOST_NOT_ALLOWLISTED` | URL 主机与声明发布者不匹配 | 修正 publisher code/URL，并在外部法律流程独立核验来源 |
| `SOURCE_HASH_STATUS_INVALID` | JSON 试图声称当前没有的抓取/哈希证明 | 保持 `DECLARED_UNVERIFIED`；不得通过改名冒充已验证 |
| `DATE_FORMAT_INVALID` / `DATE_INTERVAL_INVALID` | 格式、真实日历日期或区间顺序无效 | 使用 ISO 日期或 UTC RFC 3339；只修数据，不推断法律期限 |
| `*_SNAPSHOT_MISMATCH` / `STATE_REQUEST_MISMATCH` | 内容、依赖、statements 或请求状态变更 | 按 migration 文档的顺序重算，不复用旧报告 |
| `SCHEMA_*` / `*_FIELD_MISSING` | 结构不符合发布契约 | 对照两个 v1.3 Schema 修正；不要降级到旧 Schema |
| `REVIEW_PACKET_SCHEMA_*` / `REVIEW_PACKET_REFERENCE_*` | 三类审查包结构或包内引用不符合 v1.0 契约 | 对照审查包 Schema 修正，不增加批准字段，不删除固定限制 |
| `REVIEW_SUBJECT_SNAPSHOT_MISMATCH` / `REVIEW_SUBJECT_BINDING_MISMATCH` | 审核对象已变化或审核意见没有绑定当前对象 | 重算对象摘要并重新交叉验证；旧意见不得迁移到新对象 |
| `REVIEW_PACKET_STATUS_INVALID` / `REVIEW_DECISION_INCONSISTENT` | 状态、总意见与逐题意见不一致 | 按状态前置条件修正；全体同意也只能进入独立法律复核 |
| `OUTPUT_STATE_*` / `OUTPUT_INVALIDATION_*` | 输出状态跳级、依赖变化、历史对象或请求摘要不一致 | 降级到草稿或内部分析，重算全部受影响摘要并重新验证；不得添加 JSON 审批 |
| `CASE_WORKSPACE_*` | 本地工作区来源、路径、对象、权限、集合或快照不满足不可变存储契约 | 停止使用该工作区；从仍与 intake manifest 匹配的受控来源或备份创建新工作区并完整重放，不要原地覆盖损坏对象 |
| `LEGAL_VERSION_*` / `LEGAL_RELATIONSHIP_*` | 版本、关系、区间、来源候选、无环约束或图快照不一致 | 修正未验证候选并重算版本图和下游快照；不得把结构通过解释为法律关系正确 |
| `LEGAL_TEXT_DIFF_*` | 文本非 UTF-8、超限、差异操作/摘要不一致或快照失效 | 使用安全提取的完整 UTF-8 文本重新生成；不得截断、规范化后冒充逐字差异或手改差异记录 |
| `LEGAL_FRESHNESS_*` / `OUTPUT_LEGAL_FRESHNESS_*` | 新鲜度观察不可用、陈旧、变化、派生状态或绑定错误 | 保持或降级为 `DRAFT`，重新冻结明确官方来源并生成新检查快照；正文未变也必须继续法律复核 |
| `HISTORICAL_VERSION_*` | 事件日期、地区、候选区间、状态或选择快照不一致 | 修正事件日期/版本区间后重新选择，并由独立法律审核处理过渡规则和适用性 |
| `CASE_RATE_LIMIT_*` / `CASE_COLLECTION_*` | 官方案例发布者不允许、限速间隔不足、时钟回退、账本损坏或并发锁冲突 | 停止请求并保留账本；确认来源政策和系统时钟后等待足够间隔，不要删除账本或绕过限速 |
| `OFFICIAL_CASE_*` | 冻结案例来源、分类、隐私复用状态或记录快照不一致 | 保持禁止再传播，从有效 `OFFICIAL_CASE` 冻结记录重建分类，并完成来源政策、隐私和法律复核 |

未知错误仍应 fail-closed。若错误提示与实际输入不一致，请提交不含真实案件或个人信息的最小合成复现。
