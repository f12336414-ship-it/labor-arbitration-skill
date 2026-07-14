# v0.2 → v0.3 迁移指南

v0.3.0 改变了 ID 与快照语义，旧包不能只修改 `schema_version`。保留旧包和报告为只读记录，再从原始材料重新生成。

| v0.2 / schema 1.2 | v0.3 / schema 1.3 |
| --- | --- |
| 顺序 `RAW-0001` | 路径与内容派生的 `RAW-<64 hex>` |
| 单次完整枚举 + 文件复核 | 哈希前后两次完整目录遍历 + 文件复核 |
| Python `json.dumps` 排序 | RFC 8785 / JCS |
| `document_snapshot_sha256` | `statement_snapshot_sha256` |
| 包快照排除 `requested_state` | 包快照包含 `requested_state` |
| 无独立状态请求摘要 | `state_request_sha256` |
| 清单无生成器/来源边界 | `UNATTESTED` 生成器、系统观察、时钟和 `NOT_PROVIDED` 用户来源 |
| 扩展名元数据 | 字节前缀媒体类型提示 + 扩展名不匹配标记 |
| 不表达重复/硬链接 | `DUPLICATE_CONTENT` 与 `HARDLINK_CANDIDATE` 关系 |

## 迁移步骤

1. 保留 v0.2 包、manifest 和报告，不覆盖。
2. 从可信的本地材料目录运行 v0.3 scanner，输出到扫描树外。
3. 用新 manifest 的完整 `files` 替换 `raw_files`，并更新所有 evidence 的 `raw_id`。
4. 将 `schema_version` 改为 `1.3`，加入 `snapshot_canonicalization=RFC8785`。
5. 将 `document_snapshot_sha256` 改名并按 statements 重算 `statement_snapshot_sha256`。
6. 依次重算 intake、dependency、statement、package 和 state-request 摘要；不要复用 v0.2 哈希。
7. 按两个发布 Schema 校验，再运行验证器。任何非零退出都阻断交接。
8. 将 v0.3 manifest、包、报告和未验证事项一起交给外部法律复核。

v0.3 仍不验证法律来源现行性、证据真实性或语义、时效、专业金额、管辖、主体、隐私审批、人工身份或提交权限。
