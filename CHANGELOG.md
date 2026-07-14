# Changelog

本项目按 [Semantic Versioning](https://semver.org/) 记录公开版本变化。

## [Unreleased]

### Security

- 将 CodeQL `init` 与 `analyze` 原子升级到固定 SHA 的 v4.37.0，避免拆分升级造成工作流版本不一致。

## [0.3.0] - 2026-07-14

### Changed

- 案件包与 intake manifest 升级到 schema 1.3；schema 1.2 及更旧版本 fail-closed，提供完整迁移指南。
- 所有 JSON 快照改用 RFC 8785；包快照绑定 requested state，新增 `state_request_sha256`，并将 statement-only 摘要改名为 `statement_snapshot_sha256`。
- `raw_id` 改为相对路径与内容摘要派生的稳定 ID；新增双遍目录一致性、字节前缀媒体类型、扩展名不匹配、重复内容和硬链接候选关系。
- intake manifest 增加生成器/依赖/平台、系统观察与用户来源边界、扫描时间窗口、输出权限状态和 payload 自哈希，明确全部不构成身份或构建认证。
- 验证器拆分为 finding、完整性原语、Schema、intake manifest 和来源策略模块；来源主机与哈希状态使用独立错误码。

### Security

- POSIX manifest 输出强制 `0600`；Windows 明确记录继承目录 ACL 未验证，绝对扫描根路径不写入清单。
- 两个 CLI 明确使用 UTF-8 JSON 输出与诊断契约，不再受 Windows cp1252 等宿主控制台编码影响。
- 日期启用 Draft 2020-12 format checker 和真实日历/区间语义检查。
- 运行时、测试和开发依赖均提供完整 SHA-256 锁文件；提交可复现 CycloneDX SBOM，并在 CI 运行 `pip-audit`。
- GitHub Actions 固定到完整 commit SHA；Tag 工作流生成制品、校验和、SBOM 与 GitHub build-provenance attestation。

### Testing

- 增加 Hypothesis Unicode/JCS/稳定 ID 属性测试，以及二次遍历竞态、manifest 自哈希伪造、状态绑定、日期、类型探测、重复内容和硬链接回归。
- 覆盖父进程与扫描器/验证器子进程的分支覆盖率基线为 90%，CI 合并门槛固定为 88%。

## [0.2.1] - 2026-07-14

### Changed

- 明确区分长期产品目的与当前版本任务：长期让劳动仲裁自动化的依据和缺口可追溯；当前仅提供进入外部法律复核前的本地技术交接层。
- 补充目标使用时点、技术交接包交付物、当前成功标准和重新定位条件。
- 在 README、Skill、界面元数据与机器可读能力矩阵中统一产品目的，并用仓库质量测试防止再次漂移。

## [0.2.0] - 2026-07-14

### Changed

- 将产品边界收缩为“劳动仲裁引用完整性内核”，自动化上限改为 `REFERENCE_INTEGRITY_VALIDATED`。
- 升级案件包与 intake manifest 到 schema 1.2；旧 schema 和旧机器/提交状态 fail-closed。
- 法律规则、证据支持、举证责任、时效、金额、请求冲突、隐私和风险处置统一改为未验证或外部待复核语义。
- 增加机器可读能力矩阵、v0.2 二次审核、ADR、迁移指南与明确的用户流程。

### Security

- 拒绝 JSON 冒充人工审批、隐私审核或 P0/P1 风险关闭。
- 材料扫描改用稳定打开句柄并检查读前/读后/最终路径元数据。
- 不再把 Windows 已弃用且语义可能变化的 `st_ctime_ns` 作为内容稳定信号；仍校验文件身份、类型、大小、`st_mtime_ns` 与实际读取字节数。
- 拒绝符号链接、junction/重解析点、挂载点、特殊文件与网络根目录。
- 增加文件数、单文件、总量、目录深度和扫描截止时间上限；失败不发布部分清单。
- 增加官方来源候选主机过滤，但明确不提供抓取、固化、现行性或适用性验证。

### Testing

- 增加 Draft 2020-12 Schema 元校验和完整安全样本校验。
- 增加并发文件变化、重解析入口、资源上限、降级绕过和所有 P0 信任边界回归测试。

## [0.1.0] - 2026-07-14

### Added

- Codex Skill 元数据、北京场景可靠性契约和输出状态机。
- 只读材料清单生成器，包含稳定排序、SHA-256、符号链接隔离和原子写入。
- 案件包确定性验证器，覆盖来源、证据、事实、请求、时效、计算、隐私、对抗复核和人工批准门禁。
- 损坏 JSON、重复键、非标准数值、超大输入和结构异常的 fail-closed 处理。
- 跨平台测试、CodeQL、依赖审查和开源治理文件。
