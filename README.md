# 劳动仲裁引用完整性内核

[![CI](https://github.com/f12336414-ship-it/labor-arbitration-skill/actions/workflows/test.yml/badge.svg)](https://github.com/f12336414-ship-it/labor-arbitration-skill/actions/workflows/test.yml)
[![CodeQL](https://github.com/f12336414-ship-it/labor-arbitration-skill/actions/workflows/codeql.yml/badge.svg)](https://github.com/f12336414-ship-it/labor-arbitration-skill/actions/workflows/codeql.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

技术标识仍为 `labor-arbitration-skill`，以保持安装路径和调用方式兼容。它是本地、只读优先的参考完整性工具，不是完整劳动仲裁产品，也不是律师、法律服务、证据鉴定或提交系统。

v0.2.0 的自动化上限是 `REFERENCE_INTEGRITY_VALIDATED`：只表示 v1.2 结构、标识符、引用、快照、材料清单和通用算术重算通过。下一状态固定为 `PENDING_LEGAL_REVIEW`。`allowed=true` 也只适用于请求的技术状态，不代表法律正确、材料真实或可以提交。

## 能力边界

| 状态 | 能力 | 说明 |
| --- | --- | --- |
| 已实现 | 有界本地文件扫描、稳定句柄 SHA-256、原子清单 | 哈希描述扫描时读取的字节，不证明真实性或后续未变 |
| 已实现 | JSON 结构、ID、引用、清单与快照一致性 | 不判断事实、证据、规则或文书内容是否正确 |
| 已实现 | `SUM_DECIMAL_INPUTS_V1` 十进制重算 | 只证明加法与舍入一致，不是劳动法金额公式 |
| 部分 | 官方来源候选域名过滤 | 只检查 HTTPS、发布者代码和主机名，不抓取、不固化、不验证现行有效或逐字一致 |
| 部分 | 证据位置、请求要素、时效事件的数据结构 | 只检查引用存在，不进行 OCR、语义支持、要件充分性或时效计算 |
| 未实现 | 北京权威规则包、时效引擎、专业请求计算器、竞合矩阵 | 禁止产生对应法律结论 |
| 未实现 | 管辖、用人单位主体、提交材料生成、真实案件评测 | 禁止声称支持实际提交 |
| 未实现 | 登录、RBAC、签名审批、不可抵赖审计、SaaS 隐私/备份 | JSON 中的 `HUMAN` 或姓名永远不是批准证明 |

完整机器可读清单见 [capabilities.json](labor-arbitration-skill/references/capabilities.json)。

## 快速开始

运行时要求 Python 3.10 或更高版本，并使用固定版本的 `jsonschema` 执行完整 v1.2 结构校验。

```powershell
git clone https://github.com/f12336414-ship-it/labor-arbitration-skill.git
cd labor-arbitration-skill
python -m pip install -r requirements-dev.txt
cd labor-arbitration-skill
python -m unittest discover -s tests -v
```

先在仓库根目录安装运行时依赖：

```powershell
python -m pip install -r labor-arbitration-skill/requirements.txt
```

再将 `labor-arbitration-skill` 子目录复制或链接到个人 Codex skills 目录，然后显式调用 `$labor-arbitration-skill`。如果复制后会脱离本仓库，必须连同子目录内的 `requirements.txt` 一并保留并安装。

登记本地材料，输出必须位于材料目录之外：

```powershell
python scripts/build_intake_manifest.py <材料目录> --output <manifest.json>
```

扫描器默认限制为 10,000 个文件、单文件 100 MiB、总量 1 GiB、目录深度 20、60 秒；可用 `--max-files`、`--max-file-bytes`、`--max-total-bytes`、`--max-depth`、`--timeout-seconds` 收紧。链接、junction、重解析点、挂载点、特殊文件、网络根目录、读取竞态或超限会阻止清单生成。

验证结构化案件包：

```powershell
python scripts/validate_case_package.py <case-package.json> --intake-manifest <manifest.json>
```

退出码：`0` 表示所请求的技术状态通过；`2` 表示输入可解析但安全门禁阻断；`1` 表示输入损坏、超限或不可读。报告中的 `validation_scope.not_verified` 是必须继续人工或外部系统处理的能力。

[JSON Schema](labor-arbitration-skill/references/case-package.schema.json) 是 v1.2 结构契约；[合成草稿](examples/synthetic-draft.json)不含真实案件数据。

## 状态流

```mermaid
flowchart LR
    A["不可信材料"] --> B["INGESTION_BYTES_OBSERVED"]
    B --> C["DRAFT / REVIEW_REQUIRED"]
    C --> D["REFERENCE_INTEGRITY_VALIDATED"]
    D --> E["PENDING_LEGAL_REVIEW（外部）"]
    E --> F["认证审批与提交（本项目未实现）"]
```

旧的 `MACHINE_VALIDATED_CANDIDATE` 与 `HUMAN_APPROVED_FOR_SUBMISSION` 已弃用并阻断，schema 1.1 也不再受支持，避免通过降级绕过安全边界。

## 官方来源候选主机

当前过滤表仅覆盖国家法律法规数据库、国务院、最高人民法院、人力资源社会保障部、北京市政府和北京市人社局的少量主机。候选来源可从[国家法律法规数据库](https://flk.npc.gov.cn/)、[最高人民法院](https://www.court.gov.cn/)、[人力资源社会保障部](https://www.mohrss.gov.cn/)、[北京市人民政府](https://www.beijing.gov.cn/)和[北京市人力资源和社会保障局](https://rsj.beijing.gov.cn/)进入。白名单命中不证明具体页面由声明机关发布，也不证明文件有效、完整或适用于案件。

## 文档与治理

- [v0.2 二次审核报告](docs/audit-v0.2.md)
- [可靠性契约](labor-arbitration-skill/references/reliability-contract.md)
- [威胁模型](docs/threat-model.md)
- [v0.2 架构决策](docs/adr/0001-truthful-trust-boundary-v0.2.md)
- [迁移指南](docs/migration-v0.2.md)
- [v1.0 生产门禁路线图](https://github.com/f12336414-ship-it/labor-arbitration-skill/milestone/1)：所有真实案件法律判断或提交就绪声明的阻断项

项目采用 [Apache License 2.0](LICENSE)。贡献前阅读 [CONTRIBUTING.md](CONTRIBUTING.md)、[SECURITY.md](SECURITY.md) 和 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。只允许合成测试数据；真实姓名、身份证号、联系方式、工资记录、聊天记录、审批凭证和案件材料不得进入仓库、Issue、PR 或 CI 日志。
