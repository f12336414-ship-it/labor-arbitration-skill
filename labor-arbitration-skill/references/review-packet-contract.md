# 三类交叉验证审查包契约

## 目的

本契约把 Codex 提出的规则、请求权和计算公式候选项整理为可逐项交叉验证、可绑定版本的 JSON 审查包。它解决“审核对象是什么、依据是什么、审核意见绑定了哪个版本”的问题，不解决法律正确性、审核人身份认证、专业签署或材料提交批准。

发布结构以 [review-packet.schema.json](review-packet.schema.json) 为准，确定性策略以 `scripts/review_packet_policy.py` 为准。

## 三种审查对象

| `packet_type` | 审查内容 | 固定未验证状态 |
| --- | --- | --- |
| `RULE_REVIEW` | 规则命题、条文定位、适用条件、例外、生效区间及受影响对象 | `UNVERIFIED_CANDIDATE` |
| `CLAIM_REVIEW` | 请求权要件、候选救济路径、举证阶段、时效输入、抗辩和竞合关系 | `UNVERIFIED_CANDIDATE`，时效为 `UNVERIFIED` |
| `CALCULATOR_REVIEW` | 输入、候选公式、舍入、动态参数、冲突检查和黄金测试向量 | `FORMULA_CANDIDATE_UNVERIFIED`，不得产生法律金额 |

请求权和计算器包中的每个 `rule_id` 必须有且只有一条 `rule_dependencies` 记录，声明所依赖规则包的 ID、审核对象摘要和完整包摘要；要件、时效、输入和动态参数中的规则引用只能指向这些依赖。单包验证只确认引用闭合和版本字段存在，不能证明外部规则包真实存在或内容正确，因此依赖状态固定为 `DECLARED_UNVERIFIED`。

仓库只发布不含真实法律结论和案件数据的合成草稿：

- [规则示例](../../examples/review-packets/synthetic-rule-review.json)
- [请求权示例](../../examples/review-packets/synthetic-claim-review.json)
- [计算器示例](../../examples/review-packets/synthetic-calculator-review.json)

## 状态语义

| 状态 | 必要条件 | 后续动作 |
| --- | --- | --- |
| `DRAFT_FOR_CROSS_VALIDATION` | 不得已有交叉验证记录 | 项目交叉验证 |
| `CROSS_VALIDATION_RECORDED` | 至少一条结构完整、绑定当前对象的记录 | 按意见修订或进入独立法律复核 |
| `REVISION_REQUIRED` | 至少一个问题不同意或需要更多依据 | 修订对象并使旧审核绑定失效 |
| `PENDING_INDEPENDENT_LEGAL_REVIEW` | 所有已记录问题均为同意 | 独立、可认证的专业法律复核 |

项目交叉验证只能使用：

- `reviewer_role: PROJECT_CROSS_VALIDATOR`；
- `authentication_status: UNAUTHENTICATED_SELF_DECLARATION`；
- `legal_approval_effect: NONE`。

因此，即使全部问题为 `AGREE`，结果仍固定为 `submission_ready: false`，不能转换成批准或可提交状态。

## 快照绑定

`review_subject_sha256` 是以下对象按 RFC 8785 规范化后的 SHA-256：`schema_version`、`packet_id`、`packet_type`、`jurisdiction`、`source_artifacts`、`subject`、`review_questions` 和 `limitations`。

每条 `cross_validation` 记录必须保存相同的 `review_subject_sha256`。上述任一内容变化时，必须生成新的对象摘要并重新审核，旧意见不得迁移。

`packet_snapshot_sha256` 是除自身字段外完整审查包的 RFC 8785 SHA-256。新增或修改审核记录、状态或其他字段后必须重算该摘要。

## 交叉验证步骤

1. Codex 生成 `DRAFT_FOR_CROSS_VALIDATION` 草稿和候选官方来源；来源内容仍标为 `DECLARED_UNVERIFIED`。
2. 运行验证器，确认结构、引用和快照没有错误。
3. 审核者逐题选择 `AGREE`、`DISAGREE` 或 `NEEDS_MORE_EVIDENCE`，填写说明；同意或不同意必须引用至少一个包内来源 ID。
4. 记录意见后重算完整包摘要并再次验证。
5. 不同意或缺依据时修订审查对象并重新开始；全部同意时只能进入独立法律复核。

在 Skill 目录运行：

```powershell
python scripts/validate_review_packet.py <review-packet.json>
```

退出码 `0` 只表示发布 Schema、引用、状态与 RFC 8785 绑定通过；`2` 表示可解析但门禁阻断；`1` 表示输入损坏、超限或不可读。报告中的 `validation_scope.not_verified` 必须原样保留。

## 明确不验证

- 候选来源内容是否真实、完整、现行或适用于具体案件；
- 规则命题、请求权要件、举证责任、时效或公式是否法律正确；
- 审核者身份、资格、授权或签署有效性；
- 真实案件事实、证据证明力或金额；
- 专业法律批准和提交就绪状态。
