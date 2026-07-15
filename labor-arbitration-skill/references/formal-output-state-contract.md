# 正式输出技术状态契约

## 目的

本契约证明一个输出对象申请的技术状态绑定了哪一组案件、法律来源、分析、计算和文书摘要，并在依赖变化后强制失效。它不认证法律审核者、批准或提交资格。

发布结构以 [formal-output-state.schema.json](formal-output-state.schema.json) 为准，确定性策略以 `scripts/formal_output_state_policy.py` 为准。

## 状态

| 状态 | 当前允许 | 含义 |
| --- | --- | --- |
| `INTERNAL_ANALYSIS` | 是 | 内部探索；不得作为正式材料 |
| `DRAFT` | 是 | 可阅读草稿；允许存在缺口和未检查新鲜度 |
| `REVIEW_REQUIRED` | 仅建模，当前阻断 | 未来技术依赖全部可验证后，等待独立法律复核 |
| `SUBMISSION_CANDIDATE` | 否 | 需要未来的法律新鲜度、身份、审批、签名和审计系统 |

首次请求只能进入 `INTERNAL_ANALYSIS`。合法升级为：

```text
INTERNAL_ANALYSIS -> DRAFT -> REVIEW_REQUIRED
```

同状态重新生成和向较低状态降级允许。由于当前尚无权威规则包、专业计算器和完整分析门禁，验证器也阻断 `REVIEW_REQUIRED`；这保持了 v0.3 的自动化状态上限。当前实现永远阻断 `SUBMISSION_CANDIDATE`，非空 `approvals` 也不符合 Schema。

## 依赖失效

`dependency_snapshots` 固定包含：案件、法律来源、分析、计算和文书五个 RFC 8785/SHA-256 摘要。存在 `previous_binding` 时，验证器会自行计算变化集合：

- 无变化：`invalidation.status` 必须为 `CURRENT`；
- 有变化：状态必须为 `INVALIDATED_BY_DEPENDENCY_CHANGE`，变化类别必须完全一致；
- 任一依赖变化时，不得保持或升级为 `REVIEW_REQUIRED`，只能回到 `DRAFT` 或 `INTERNAL_ANALYSIS` 后重新验证。

`previous_binding` 必须声明相同的 `artifact_id` 和 `artifact_type`，防止借用其他输出的状态历史。`state_request_sha256` 是除自身字段外完整请求的 RFC 8785 SHA-256。旧状态请求只能作为历史证据，不能在依赖变化后复用。

`legal_freshness` 同时绑定技术新鲜度状态、`check_id` 和检查快照。首次未检查时三者必须为 `NOT_CHECKED/null/null`；其他状态必须绑定非空检查 ID 和 SHA-256。新鲜度绑定相对前一状态发生任何变化，都按 `LEGAL_SOURCES` 依赖变化处理。`CHANGE_DETECTED_REVIEW_REQUIRED`、`UNAVAILABLE_DRAFT_ONLY`、`STALE_DRAFT_ONLY` 或未检查状态只能保留在草稿层；`UNCHANGED_RESPONSE_BODY_CANDIDATE` 也只证明所比较响应正文未变，不授予升级或法律现行性。具体见[法律来源版本、差异与新鲜度技术契约](legal-source-versioning-contract.md)。

单文件校验只确认前一请求摘要和字段的声明闭合，不证明对应历史文件真实存在或曾被可信系统接受；该属性继续列在 `validation_scope.not_verified`，直到未来的不可变状态存储和认证审计实现。

## 使用

```powershell
python scripts/validate_formal_output_state.py <state-request.json>
```

退出码 `0` 只表示状态、依赖、失效声明和快照满足当前技术契约；`2` 表示可解析但门禁阻断；`1` 表示输入损坏、超限或不可读。成功报告仍固定 `submission_ready: false` 和 `legal_review_required: true`。
