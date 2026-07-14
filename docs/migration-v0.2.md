# v0.1 → v0.2 迁移指南

v0.2.0 是安全边界变更。旧包不能通过修改一个版本号继续使用；必须重新登记材料、迁移字段并生成所有快照。

| v0.1 | v0.2 |
| --- | --- |
| schema `1.1` | schema `1.2` |
| `INGESTION_INTEGRITY_VERIFIED` | `INGESTION_BYTES_OBSERVED` |
| `MACHINE_VALIDATED_CANDIDATE` | `REFERENCE_INTEGRITY_VALIDATED` |
| `HUMAN_APPROVED_FOR_SUBMISSION` | 删除；转入外部认证审批系统 |
| `VERIFIED_CURRENT/HISTORICAL` | `UNVERIFIED_CANDIDATE` |
| `reviewer_actor_type=HUMAN` | 删除权威含义；相关字段保持 `null` 或空数组 |
| `SUPPORTED` | `EVIDENCE_LINKED_UNVERIFIED` |
| `TRIBUNAL_FOUND/CORROBORATED` | 不支持；外部核验前不得迁移为权威事实 |
| `initial_burden_satisfied` | `initial_burden_status=UNVERIFIED` |
| 已计算时效与 within/outside | `calculated_deadline=null`、`deadline_status=UNVERIFIED` |
| `EXACT_GIVEN_ASSUMPTIONS` | `ARITHMETIC_RECOMPUTED` |
| 冲突 `RESOLVED` | `PENDING_LEGAL_REVIEW` |
| 隐私 `COMPLETED` | `EXTERNAL_REVIEW_REQUIRED`，审核身份字段为 `null` |

## 步骤

1. 保留旧包为只读历史记录，不覆盖。
2. 使用 v0.2 扫描器重新生成 v1.2 intake manifest。
3. 将 raw/evidence 完整性状态改为字节观察语义。
4. 将规则、事实、证明、时效、金额、冲突、隐私和审批字段收缩到上表状态。
5. 对照 [case-package.schema.json](../labor-arbitration-skill/references/case-package.schema.json) 校验结构。
6. 重新计算 intake、dependency、document 和 package 快照。
7. 运行验证器；不要复用 v0.1 的通过报告或审批记录。
8. 将成功报告与锁定包交给本项目之外的认证法律复核流程。

任何无法诚实迁移到“未验证/待复核”的旧字段都应删除并记录为迁移缺口，不能猜测填充。
