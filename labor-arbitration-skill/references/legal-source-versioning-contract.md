# 法律来源版本、差异与新鲜度技术契约

## 能证明什么

本契约把已经冻结的候选官方来源组织为可重放的技术记录：

- 版本图记录发布、修改、废止、替代、纠正和冲突候选关系；
- 精确文本差异绑定两个 UTF-8 正文哈希，不做 Unicode 规范化，不截断超限差异；
- 新鲜度记录把基线正文与后续受控冻结正文比较，并绑定 RFC 8785 检查快照；
- 历史版本选择只按案件事件日期、地区和声明的候选生效区间筛选。

上述记录都只证明结构、哈希、区间或字节比较一致。它们不证明发布者身份、法律效力、现行性、溯及力、过渡规则或案件适用性。

## 版本图和精确差异

版本图见 [legal-version-graph.schema.json](legal-version-graph.schema.json)。每个版本绑定冻结记录快照和正文 SHA-256；每条关系绑定依据快照和 [legal-text-diff.schema.json](legal-text-diff.schema.json) 的差异快照。修改、废止、替代和纠正关系必须无环，但“无环”不等于关系在法律上正确。

对已经安全提取为 UTF-8 的文本运行：

```powershell
python scripts/compare_legal_versions.py <旧文本> <新文本> `
  --from-version-id <旧版本ID> --to-version-id <新版本ID>
python scripts/validate_legal_text_diff.py <差异记录.json>
python scripts/validate_legal_version_graph.py <版本图.json>
```

差异器最多接受每份 1 MiB UTF-8 文本，完整差异记录最多 4 MiB。PDF、HTML 到纯文本的提取不属于本契约；输入文本过大、非 UTF-8 或差异过大时拒绝，绝不以截断结果冒充完整差异。

## 新鲜度

新鲜度记录见 [legal-freshness-check.schema.json](legal-freshness-check.schema.json)。运行：

```powershell
python scripts/validate_legal_freshness.py <新鲜度记录.json>
```

状态含义：

| 状态 | 技术含义 | 输出限制 |
| --- | --- | --- |
| `UNCHANGED_RESPONSE_BODY_CANDIDATE` | 后续冻结正文哈希未变且未超过技术最大年龄 | 只允许绑定检查快照，不自动升级 |
| `CHANGE_DETECTED_REVIEW_REQUIRED` | 后续正文哈希改变 | 必须保持或降级为 `DRAFT` 并重新审核 |
| `UNAVAILABLE_DRAFT_ONLY` | 网络或官方来源不可确认 | 只能 `DRAFT` |
| `STALE_DRAFT_ONLY` | 绑定的成功观察超过最大年龄 | 只能 `DRAFT` |

正式输出状态必须同时绑定 `check_id` 和 `check_snapshot_sha256`。任何新鲜度绑定变化都按 `LEGAL_SOURCES` 依赖变化处理。正文未变仍不能证明法律未被其他文件修改、废止或解释。

当前实现提供确定性的检查记录和提交前门禁，但没有后台调度服务；定期触发、告警和错误预算仍属于 P2-10。因此 P2-05 只达到技术基础状态，不宣称端到端定期监控完成。

## 历史候选

运行：

```powershell
python scripts/select_historical_version.py <版本图.json> --event-date YYYY-MM-DD
python scripts/validate_historical_version.py <历史候选.json>
```

输出只能是 `UNIQUE_CANDIDATE`、`MULTIPLE_CANDIDATES` 或 `NO_CANDIDATE`。即使只有一个区间候选，仍固定 `PENDING_INDEPENDENT_LEGAL_REVIEW`；特别过渡条款、冲突规则和溯及力必须由独立法律审核确定。
