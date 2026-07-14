# v0.2 二次审核报告

审核日期：2026-07-14

审核对象：公开版本 v0.1.0、附件中的 P0–P3 二次审核意见，以及 v0.2.0 加固实现。

结论：附件判断总体成立。v0.1.0 是可靠性框架原型，不是真实劳动仲裁法律能力。真实案件法律决策与提交为 `NOT_READY`；v0.2.0 仅对本地引用完整性用途为 `READY_WITH_ASSUMPTIONS`。

## 1. 设计门禁

完整生产能力缺少法律领域负责人、风险负责人、权威规则内容与更新服务、身份与签名基础设施、部署/租户边界、隐私治理和真实案件验收指标。直接实现“现行法律验证、时效结论、专业金额、人工批准、完整北京规则包、证据语义支持”会制造虚假保证，因此未通过正式生产设计门禁。

本次允许的可逆切片是：收缩名称与状态、输出机器可读能力边界、阻断未经验证的法律/证据/身份结论、修复扫描工程风险、发布迁移和阻断路线图。

## 2. P0 复核

| 编号 | 二审判断 | v0.1 证据 | v0.2 处置 | 剩余状态 |
| --- | --- | --- | --- | --- |
| P0-1 法律来源未真正验证 | 成立 | 只检查 URL 形态、字段、哈希格式和 `HUMAN` 字符串，不抓取或冻结 | 规则只能为 `UNVERIFIED_CANDIDATE`；增加少量官方候选主机过滤；报告明确未验证现行性与适用性 | 抓取、重定向、固化、版本、逐字比对和更新服务未实现，生产阻断 |
| P0-2 机器验证状态误导 | 成立 | `MACHINE_VALIDATED_CANDIDATE` 容易被理解为法律通过 | 改为 `REFERENCE_INTEGRITY_VALIDATED`；报告列出 verified/not_verified；旧状态和 schema 1.1 阻断 | 外部法律复核仍必须 |
| P0-3 无确定性时效引擎 | 成立 | 接受调用方填写的截止日和 within/outside 结论 | 截止日强制 `null`，状态强制 `UNVERIFIED/PENDING_LEGAL_REVIEW` | 时效引擎未实现，生产阻断 |
| P0-4 通用加法不等于专业金额 | 成立 | 唯一公式是通用小数求和 | 只允许 `ARITHMETIC_RECOMPUTED`；报告明确专业请求计算未验证 | 专业计算器与竞合规则未实现，生产阻断 |
| P0-5 JSON 可冒充人工审批 | 成立 | 完整字符串字段可获得提交批准态 | 删除提交批准能力；非空审批、隐私批准和 P0/P1 关闭字段全部拒绝 | 认证、RBAC、签名、职责分离、不可抵赖审计未实现 |
| P0-6 缺少北京规则包 | 成立 | 只有范围声明，没有经法律审核的内容库 | 产品表述改为“北京声明范围”，能力矩阵标记未实现 | 权威规则包和更新治理未实现，生产阻断 |
| P0-7 ID 关联不证明证据支持 | 成立 | 只检查 `fact -> evidence` ID 存在 | 证明状态改为 `EVIDENCE_LINKED_UNVERIFIED`；禁止 corroborated/tribunal/support 状态 | 提取、锚点实存、语义、矛盾、真实性和人工确认未实现 |

## 3. P1 复核

全部基本成立：v0.1 的材料能力是“文件清单与哈希”，不是 PDF/Office/OCR/音视频/聊天解析；不存在完整请求权要件目录、竞合矩阵、管辖引擎、用人单位主体核验、仲裁材料生成或真实案件法律评测。

v0.2 没有用示例规则伪装完成上述能力，而是：

- 在 [capabilities.json](../labor-arbitration-skill/references/capabilities.json) 标记 `PARTIAL` 或 `NOT_IMPLEMENTED`；
- 禁止 `TRIBUNAL_FOUND`、`CORROBORATED`、自报初步举证责任满足和自报冲突解决；
- 将非空冲突保持为 `PENDING_LEGAL_REVIEW`；
- 保留纯引用图和数据收集结构，避免丢失未来迁移路径。

## 4. P2 复核

| 项目 | 结论与处置 |
| --- | --- |
| 扫描 stat/open 竞态 | 成立。改为同一打开句柄读前/读后 `fstat`、读出字节计数和最终路径复核；并发修改测试阻断。 |
| Windows junction/reparse | 成立。根目录先 `lstat` 后解析；树内符号链接、重解析点、挂载点和特殊文件全部拒绝。 |
| 文件数/大小/深度/时间 | 成立。加入默认上限、CLI 收紧参数、稳定错误码和无部分输出行为。 |
| 修改后审批失效 | v0.1 已有包快照变更与审批快照失配测试，这一小点并非完全缺失；但身份不可验证更严重，因此 v0.2 直接删除本地批准能力。 |
| 审计日志、备份、版本恢复 | 未实现；本地参考内核不声明具备。 |
| SaaS/隐私 | 未实现；外部模型、托管、多用户和真实数据治理继续 `NOT_READY`。 |

## 5. P3 复核

成立。仓库技术名为兼容保留，产品显示名改为“劳动仲裁引用完整性内核”。README 和 Skill 使用“已实现/部分/未实现/禁止”的能力表达，并给出从扫描到外部法律复核的用户流。

## 6. 验收证据

- v1.2 Schema 与完整安全样本通过 Draft 2020-12 元校验和实例校验。
- Windows 实测覆盖符号链接/重解析入口、并发文件变化、扫描资源上限和原子输出。
- 验证器覆盖旧 schema 降级、旧状态、伪造审批、伪造隐私审核、伪造风险关闭、伪造现行规则、时效结论、法律金额、证据语义和事实权威状态。
- CI 继续覆盖 Windows、macOS、Ubuntu 与 Python 3.10/3.14；CodeQL 和依赖审查保留。

## 7. 最终评价

v0.2.0 可作为开源的“劳动仲裁引用完整性内核”继续研发和审查，但不得用于形成真实案件的法律结论、金额、时效判断、管辖选择、证据证明力判断或提交批准。完整劳动仲裁产品仍约为二审所评的 3–4/10；本次发布提升的是诚实边界和工程安全，不是法律办案能力。

## 8. v1.0 生产阻断路线图

以下事项统一归入 [v1.0-production-gates](https://github.com/f12336414-ship-it/labor-arbitration-skill/milestone/1)。在其对应验收证据和外部负责人全部到位前，不得提高本报告的真实案件结论：

- [#6 北京权威规则包与来源治理](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/6)
- [#7 分请求权法律时效引擎](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/7)
- [#8 专业请求计算器与救济竞合矩阵](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/8)
- [#9 认证审批、RBAC、签名与不可变审计](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/9)
- [#10 证据提取、锚点、语义与人工确认](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/10)
- [#11 请求权目录、管辖、主体与提交文书](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/11)
- [#12 受治理真实案件法律评测](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/12)
- [#13 托管服务隐私、安全、备份与保留](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/13)
