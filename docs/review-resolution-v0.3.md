# v0.3 复审处置与验收证据

审核日期：2026-07-14
输入：`labor-arbitration-skill-重新审查与改进建议-2026-07-14.md`
发布目标：v0.3.0 / schema 1.3

## 结论

复审指出的本地核心工程问题已实现、反证或转为有验收条件的明确门禁。真实法律能力、真实案件评测、认证审批和托管隐私安全不能由仓库代码单方完成，继续为生产阻断项；把它们标成“已完成”会制造新的 P0。

## 可本地闭环项

| 复审项 | 处置 | 证据 |
| --- | --- | --- |
| P1-01 版本漂移 | 旧发现已被 v0.2.1 当前证据反证；v0.3 再统一版本 | `VERSION`、CHANGELOG、capabilities、Schema、Skill 和质量测试统一为 0.3.0/1.3 |
| P1-02 生成器来源 | 不伪造签名；清单记录代码/依赖摘要、平台与 `UNATTESTED`，Tag 制品使用 GitHub provenance | manifest `generator`、`manifest_payload_sha256`、`release-provenance.yml` |
| P1-03 顺序 ID | 已修复 | 路径+内容 SHA-256 稳定 ID；属性测试与插入文件回归 |
| P1-04 单次枚举 | 已修复 | 第二次完整目录遍历；新增文件竞态回归 |
| P1-05 provenance | 已修复为诚实边界 | 系统观察、用户声明、生成器真实性分字段；均不冒充认证 |
| P1-06 日期 | 已修复 | JSON Schema format checker、RFC 3339 UTC、真实日历日期、规则区间顺序测试 |
| P1-07 错误码混合 | 已修复 | `SOURCE_HOST_NOT_ALLOWLISTED` 与 `SOURCE_HASH_STATUS_INVALID` 分离 |
| P1-08 状态扩展 | 已设计且当前 fail-closed | `trust-state-machine.md`；未来状态当前全部拒绝 |
| P1-09 Python 排序 | 已修复 | RFC 8785 依赖、UTF-16 键顺序向量、Unicode 属性测试 |
| P1-10 状态未绑定 | 技术绑定已修复；身份授权仍外部阻断 | package snapshot 包含 requested state；新增 `state_request_sha256` |
| P1-11 document 命名 | 已修复 | 改为 `statement_snapshot_sha256`；报告明确 rendered document 未实现 |
| P1-12 输出安全 | 本地可闭环部分已修复 | 不输出绝对根路径；POSIX `0600`；Windows ACL 未验证和相对文件名敏感性写入清单 |
| P1-13 单文件过大 | 已按稳定策略边界拆分 | finding、RFC 8785/哈希/日期/稳定 ID、Schema、intake manifest 与来源策略均为独立模块；主文件只保留案件门禁编排 |
| P1-14 测试不足 | 已补强 | Hypothesis、Unicode/JCS、目录竞态、manifest 伪造、硬链接、日期与状态绑定测试；3 OS × 2 Python CI；父进程和 CLI 子进程综合分支覆盖率基线 90%，合并门槛 88% |
| P2 供应链 | 已修复 | 全依赖哈希锁、`pip-audit`、CycloneDX SBOM、固定 SHA Actions、Tag provenance workflow |
| P2 类型识别 | 已修复为安全提示 | 字节魔数/UTF-8 启发式，不执行、不深度解析 |
| P2 重复与硬链接 | 已修复 | manifest 派生关系并由 validator 重算 |
| P2 大对象 | 不提高 10 MiB 上限 | 大对象/CAS 仍属未来设计；保持 fail-closed 比无界加载安全 |
| P2 错误可操作性 | 已修复基础层 | 每条 finding 增加中文提示与 remediation；保留稳定 code/path |

## 不能由本次代码伪造关闭的 P0

以下门禁已具备公开 Issue、边界和验收方向，但状态仍为 `EXTERNAL_BLOCKED`：

- [#6 北京权威规则包与来源治理](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/6)
- [#7 分请求权法律时效引擎](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/7)
- [#8 专业请求计算器与救济竞合矩阵](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/8)
- [#9 认证审批、RBAC、签名与不可变审计](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/9)
- [#10 证据提取、锚点、语义与人工确认](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/10)
- [#11 请求权目录、管辖、主体与提交文书](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/11)
- [#12 受治理真实案件法律评测](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/12)
- [#13 托管服务隐私、安全、备份与保留](https://github.com/f12336414-ship-it/labor-arbitration-skill/issues/13)

在有资质法律负责人、隐私/安全负责人、真实受治理数据、认证基础设施和独立验收证据到位前，本项目不得输出真实案件法律正确、时效正确、金额正确、可提交或已批准等结论。
