# 来源与状态证明模型

## 当前可接受状态

v0.3 只接受 `content_hash_status=DECLARED_UNVERIFIED` 和规则状态 `UNVERIFIED_CANDIDATE`。这表示调用方提供了 URL 与哈希形状，验证器只检查结构、HTTPS 和候选主机；它没有观察网络响应或证明发布者、内容、版本、现行性、适用性。

## 未来状态及最低证明

以下状态是设计保留项，当前 Schema 和验证器全部拒绝：

| 未来状态 | 最低机器证明 | 仍需外部证明 |
| --- | --- | --- |
| `FETCH_BYTES_OBSERVED` | 固定请求策略、最终 URL/重定向链、响应元数据、原始响应字节、内容 SHA-256、抓取器版本 | 发布者身份、法律效力 |
| `PUBLISHER_ORIGIN_AUTHENTICATED` | 受信 TLS/签名证据、域名与发布者注册映射、可重放验证记录 | 文件是否为有效规范性文本 |
| `VERSION_RELATIONSHIP_VERIFIED` | 不可变版本库、修订/废止关系、逐字差异、更新时间与监控记录 | 法律审核者确认版本关系 |
| `LEGAL_CURRENTNESS_REVIEWED` | 绑定到具体内容哈希、版本图和审核策略的认证签名 | 有资质法律负责人、复核期限 |
| `CASE_APPLICABILITY_REVIEWED` | 绑定案件快照、管辖与时间点的认证决定 | 对具体案件的专业法律判断 |

状态只能在前一状态证明完整、转换策略版本固定、转换结果绑定输入摘要、执行身份可认证、审计记录不可变时前进。单个 JSON 字段、姓名、时间、URL、哈希或 `HUMAN` 字符串不能完成转换。

## 技术状态与权限状态

`state_request_sha256` 只防止 v1.3 包的请求状态与快照被静默拆开。它不是签名、登录、RBAC、职责分离、法律批准或提交授权。`REFERENCE_INTEGRITY_VALIDATED` 后的唯一规定动作仍是外部 `PENDING_LEGAL_REVIEW`。
