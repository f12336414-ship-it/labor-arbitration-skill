# 劳动仲裁引用完整性内核

[![CI](https://github.com/f12336414-ship-it/labor-arbitration-skill/actions/workflows/test.yml/badge.svg)](https://github.com/f12336414-ship-it/labor-arbitration-skill/actions/workflows/test.yml)
[![CodeQL](https://github.com/f12336414-ship-it/labor-arbitration-skill/actions/workflows/codeql.yml/badge.svg)](https://github.com/f12336414-ship-it/labor-arbitration-skill/actions/workflows/codeql.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

## 产品目的

劳动仲裁材料准备最危险的问题之一，不是 AI 不会生成文字，而是它能把遗漏的材料、断裂的引用、未经核验的规则和猜测的结论包装成一份看起来完整的结果。

本产品的长期目的是建设一套面向中国大陆劳动争议的证据整理、法律核验、请求分析、金额计算、文书生成、庭审准备和风险审查一体化办案系统。系统以案件证据为核心，以官方法律和版本核验为依据，以确定性计算、句子级来源追踪、人工复核和质量门禁控制正式输出。

> 一句话：让每个事实有证据、每个请求有要件、每个法律结论有现行依据、每个金额可复算、每份文书可追溯。

### 当前版本的任务

v0.3.0 不是完整办案系统，而是位于“材料收集/外部结构化”和“专业法律复核”之间的本地技术交接层。它把已有本地文件及外部工具生成的结构化记录整理成一个技术交接包：

1. 登记扫描时实际读取的文件字节、相对路径、大小和 SHA-256；
2. 校验 v1.3 案件包中的稳定 ID、引用、材料清单、RFC 8785 快照和状态请求绑定是否一致；
3. 重算受支持的通用小数加法；
4. 明确列出尚未验证的法律、事实、证据、时效、金额和审批范围；
5. 将锁定的案件包、清单与报告交给项目外部的法律复核流程。

它的技术标识仍为 `labor-arbitration-skill`，以保持安装路径和调用方式兼容。

### 什么时候使用

- 已经收集了一批劳动仲裁相关文件，准备让 AI、脚本或人工继续整理之前；
- 外部工具已经生成结构化事实、证据位置、候选规则或计算输入，需要检查引用是否断裂；
- 材料或结构化记录发生变化，需要证明旧快照和旧报告不能继续复用；
- 需要向法律审核者移交一份可复现的技术底稿，而不是只交一段 AI 生成文本。

如果目标是直接判断请求权、仲裁时效、金额、管辖、证据证明力或生成提交文书，当前版本不适用。

### 用户得到什么

主要交付物不是法律答案，而是一个可复查的技术交接包：`raw-file-manifest.json`、锁定的 v1.3 case package 和确定性 validation report。成功标准是复核者能够重现自动化使用了哪些字节和引用，任何相关改动都会要求重新生成快照，同时未核验问题仍然清晰可见。

完整目的、用户旅程和成功标准见[产品目的说明](docs/product-purpose.md)和[最终产品需求基线](docs/final-product-requirements.md)。

v0.3.0 的自动化上限是 `REFERENCE_INTEGRITY_VALIDATED`：只表示 v1.3 结构、标识符、引用、快照、材料清单和通用算术重算通过。下一状态固定为 `PENDING_LEGAL_REVIEW`。`allowed=true` 也只适用于请求的技术状态，不代表法律正确、材料真实或可以提交。

## 能力边界

| 状态 | 能力 | 说明 |
| --- | --- | --- |
| 已实现 | 有界本地文件扫描、稳定内容 ID、双遍目录一致性、稳定句柄 SHA-256、原子清单 | 哈希描述扫描时读取的字节，不证明真实性或后续未变 |
| 已实现 | RFC 8785 JSON、结构、ID、引用、清单、自哈希、状态请求与快照一致性 | 不判断事实、证据、规则或文书内容是否正确，也不认证生成器 |
| 已实现 | 字节魔数类型提示、重复内容与硬链接候选关系 | 仅为系统观察，不解析正文、不证明文件格式完整或安全 |
| 已实现 | `SUM_DECIMAL_INPUTS_V1` 十进制重算 | 只证明加法与舍入一致，不是劳动法金额公式 |
| 部分 | 官方来源候选域名过滤 | 只检查 HTTPS、发布者代码和主机名，不抓取、不固化、不验证现行有效或逐字一致 |
| 部分 | 证据位置、请求要素、时效事件的数据结构 | 只检查引用存在，不进行 OCR、语义支持、要件充分性或时效计算 |
| 未实现 | 北京权威规则包、时效引擎、专业请求计算器、竞合矩阵 | 禁止产生对应法律结论 |
| 未实现 | 管辖、用人单位主体、提交材料生成、真实案件评测 | 禁止声称支持实际提交 |
| 未实现 | 登录、RBAC、签名审批、不可抵赖审计、SaaS 隐私/备份 | JSON 中的 `HUMAN` 或姓名永远不是批准证明 |

完整机器可读清单见 [capabilities.json](labor-arbitration-skill/references/capabilities.json)。

## 快速开始

运行时要求 Python 3.10 或更高版本，并使用固定版本的 `jsonschema` 与 `rfc8785` 执行完整 v1.3 结构及快照校验。

```powershell
git clone https://github.com/f12336414-ship-it/labor-arbitration-skill.git
cd labor-arbitration-skill
python -m pip install --require-hashes -r requirements-test.lock
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

每条 finding 都带中文说明与修复动作；常见扫描、Schema、来源、日期和快照错误见[错误处理指南](labor-arbitration-skill/references/error-catalog.md)。

[案件包 JSON Schema](labor-arbitration-skill/references/case-package.schema.json)与[intake manifest JSON Schema](labor-arbitration-skill/references/intake-manifest.schema.json)是 v1.3 结构契约；[合成草稿](examples/synthetic-draft.json)不含真实案件数据。

## 状态流

```mermaid
flowchart LR
    A["不可信材料"] --> B["INGESTION_BYTES_OBSERVED"]
    B --> C["DRAFT / REVIEW_REQUIRED"]
    C --> D["REFERENCE_INTEGRITY_VALIDATED"]
    D --> E["PENDING_LEGAL_REVIEW（外部）"]
    E --> F["认证审批与提交（本项目未实现）"]
```

旧的 `MACHINE_VALIDATED_CANDIDATE` 与 `HUMAN_APPROVED_FOR_SUBMISSION` 已弃用并阻断，schema 1.2 及更旧版本也不再受支持，避免通过降级绕过安全边界。v0.2 包须按[迁移指南](docs/migration-v0.3.md)重新扫描和绑定，不能只修改版本号。

## 官方来源候选主机

当前过滤表仅覆盖国家法律法规数据库、国务院、最高人民法院、人力资源社会保障部、北京市政府和北京市人社局的少量主机。候选来源可从[国家法律法规数据库](https://flk.npc.gov.cn/)、[最高人民法院](https://www.court.gov.cn/)、[人力资源社会保障部](https://www.mohrss.gov.cn/)、[北京市人民政府](https://www.beijing.gov.cn/)和[北京市人力资源和社会保障局](https://rsj.beijing.gov.cn/)进入。白名单命中不证明具体页面由声明机关发布，也不证明文件有效、完整或适用于案件。

## 文档与治理

- [最终产品需求基线](docs/final-product-requirements.md)
- [最终产品实施路线图](docs/implementation-roadmap.md)
- [最终产品实时进度](docs/progress.md)
- [v0.2 二次审核报告](docs/audit-v0.2.md)
- [v0.3 复审处置与证据](docs/review-resolution-v0.3.md)
- [产品目的说明](docs/product-purpose.md)
- [可靠性契约](labor-arbitration-skill/references/reliability-contract.md)
- [威胁模型](docs/threat-model.md)
- [v0.2 架构决策](docs/adr/0001-truthful-trust-boundary-v0.2.md)
- [案件本地、法律受控联网架构决策](docs/adr/0003-local-case-data-controlled-legal-network.md)
- [迁移指南](docs/migration-v0.2.md)
- [v0.2 → v0.3 迁移指南](docs/migration-v0.3.md)
- [来源与状态证明模型](docs/trust-state-machine.md)
- [CycloneDX 运行时 SBOM](sbom.cdx.json)
- [v1.0 生产门禁路线图](https://github.com/f12336414-ship-it/labor-arbitration-skill/milestone/1)：所有真实案件法律判断或提交就绪声明的阻断项

项目采用 [Apache License 2.0](LICENSE)。贡献前阅读 [CONTRIBUTING.md](CONTRIBUTING.md)、[SECURITY.md](SECURITY.md) 和 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。只允许合成测试数据；真实姓名、身份证号、联系方式、工资记录、聊天记录、审批凭证和案件材料不得进入仓库、Issue、PR 或 CI 日志。
