# 错误处理指南

验证报告中的每条 finding 都包含稳定 `code`、字段 `path`、英文 `message`、中文 `message_zh`、`remediation` 和严重级别。修复输入后必须重新生成所有受影响的 RFC 8785 摘要，不能编辑报告来消除错误。

| 错误族 | 含义 | 处理 |
| --- | --- | --- |
| `SCAN_*_LIMIT_EXCEEDED` | 文件数、单文件、总量、深度或时间超过边界 | 缩小明确授权的输入范围，或在风险评估后显式调整对应 CLI 上限；不要删除安全检查 |
| `SCAN_*_CHANGED_DURING_READ` | 文件或整棵目录在扫描窗口内变化 | 停止写入、同步或杀毒修改，确认目录稳定后重新扫描 |
| `SCAN_REPARSE_POINT_REFUSED` / `SCAN_MOUNT_POINT_REFUSED` | 输入可能越过授权目录 | 复制所需普通文件到隔离目录，不要让 scanner 跟随链接 |
| `INTAKE_MANIFEST_*` | manifest Schema、自哈希或案件包绑定失败 | 从原始目录重新生成 manifest，并按顺序重算 intake/package/state 摘要 |
| `SOURCE_HOST_NOT_ALLOWLISTED` | URL 主机与声明发布者不匹配 | 修正 publisher code/URL，并在外部法律流程独立核验来源 |
| `SOURCE_HASH_STATUS_INVALID` | JSON 试图声称当前没有的抓取/哈希证明 | 保持 `DECLARED_UNVERIFIED`；不得通过改名冒充已验证 |
| `DATE_FORMAT_INVALID` / `DATE_INTERVAL_INVALID` | 格式、真实日历日期或区间顺序无效 | 使用 ISO 日期或 UTC RFC 3339；只修数据，不推断法律期限 |
| `*_SNAPSHOT_MISMATCH` / `STATE_REQUEST_MISMATCH` | 内容、依赖、statements 或请求状态变更 | 按 migration 文档的顺序重算，不复用旧报告 |
| `SCHEMA_*` / `*_FIELD_MISSING` | 结构不符合发布契约 | 对照两个 v1.3 Schema 修正；不要降级到旧 Schema |

未知错误仍应 fail-closed。若错误提示与实际输入不一致，请提交不含真实案件或个人信息的最小合成复现。
