# 法律更新监控与错误预算技术契约

## 1. 目的和边界

本契约解决“离线办案时如何知道需要重新联网核验”的技术问题：案件材料继续本地处理；法律公共来源由外部调度器按锁定定义触发受控抓取、冻结和检查；本地监控器确定性计算到期、漏检、变化、不可用、陈旧、连续失败和人工升级信号。

监控成功只表示“本次绑定的官方候选 URL 响应正文在技术检查范围内未变化且未超龄”。它不证明：

- 法律仍然现行、没有被其他文件修改或废止；
- 页面确由声明机关发布，或文本具有法律效力；
- 已覆盖所有上位法、解释、地方规范和过渡规则；
- 某版本适用于具体案件；
- 系统时钟、外部调度器或告警投递已经被可信认证。

因此，正文未变化时输出是 `NO_PROMOTION_GRANTED`，绝不是“法律已验证”；变化、不可用、陈旧、漏检或错误预算耗尽时必须为 `DRAFT`。

## 2. 三段式运行

1. 外部调度器按部署环境触发任务。仓库不常驻后台，也不自行安装计划任务。
2. `fetch_official_source.py` 对一个明确、已登记的 HTTPS URL 执行受控抓取并冻结原始响应；`build_legal_freshness.py` 从两个可离线重放的冻结记录构建技术新鲜度检查。网络不可用时构建 `UNAVAILABLE` 检查。
3. `build_legal_monitor_run.py` 消费锁定监控定义、直接前序运行和本批检查，计算来源状态、下次到期时间、滚动错误预算和开放告警。

监控运行本身不联网。这样可以在测试、审计和提交前门禁中重放完全相同的判断，而网络访问只发生在边界明确的冻结器中。

## 3. 锁定定义

[legal-monitor-definition-input.schema.json](legal-monitor-definition-input.schema.json) 是构建输入，[legal-monitor-definition.schema.json](legal-monitor-definition.schema.json) 是不可变记录。每个来源必须绑定：

- 唯一 `source_monitor_id` 和 `document_id`；
- 官方发布者代码、允许列表内的规范 URL；
- 已冻结的基线 ID、记录快照、正文哈希、抓取时间和最终 URL；
- 常规间隔、失败重试间隔、技术最大年龄；
- 滚动窗口、允许失败数和升级紧急度。

来源按 ID 排序，定义 ID 和快照使用 RFC 8785。定义只绑定传入的基线摘要；只有通过冻结记录离线重放后再构建新鲜度检查，才能证明摘要对应仓库中实际保存的字节。

```powershell
python scripts/build_legal_monitor_definition.py <definition-input.json>
python scripts/validate_legal_monitor_definition.py <definition.json>
```

## 4. 到期、漏检和前序链

首次运行的所有来源都视为到期。后续运行以直接前序状态中的 `next_due_at` 判断：

- 有显式检查：记录为 `CHECKED`，即使它早于到期时间；
- 已到期但无检查：记录为 `MISSED_DUE_CHECK`，计入一次失败并生成告警；
- 未到期且无检查：记录为 `CARRIED_FORWARD_NOT_DUE`，不消耗错误预算。

每次运行绑定同一监控定义和直接前序运行的 ID、快照与时间。验证派生运行时必须提供直接前序；更早历史由外部不可变存储保存。本契约不声称单个运行文件能证明整条历史未被具有写权限的人重建。

```powershell
python scripts/build_legal_monitor_run.py <run-input.json>
python scripts/validate_legal_monitor_run.py <run.json> --definition <definition.json> [--previous-run <previous.json>]
```

## 5. 告警和错误预算

状态与强制结果：

| 信号 | 告警 | 强制结果 |
| --- | --- | --- |
| 正文哈希变化 | `LEGAL_SOURCE_CHANGE_DETECTED` | `DRAFT`，禁止自动替换基线 |
| 抓取不可用 | `LEGAL_SOURCE_CHECK_UNAVAILABLE` | `DRAFT`，按失败间隔重试 |
| 成功观察超龄 | `LEGAL_SOURCE_CHECK_STALE` | `DRAFT` |
| 到期未提供检查 | `LEGAL_SOURCE_CHECK_MISSED` | `DRAFT` |
| 滚动窗口失败数超过预算 | `LEGAL_SOURCE_ERROR_BUDGET_EXHAUSTED` | `DRAFT`，高风险/关键来源升级 |

滚动结果只包含 `SUCCESS`、`UNAVAILABLE`、`MISSED`。失败数必须严格大于定义中的允许失败数才算耗尽；旧失败滑出窗口后可以恢复，但恢复仍不授予法律现行性或正式输出资格。所有告警状态均为 `OPEN_REQUIRES_HUMAN_REVIEW`；告警投递到邮件、工单或值班平台由部署方负责。

## 6. 外部调度要求

生产部署方应使用其受控的 Windows 任务计划、cron 或 CI 定时任务串行执行“抓取并冻结 → 构建检查 → 构建监控运行 → 保存不可变运行 → 投递开放告警”。调度凭据、代理、网络许可、日志保留和告警接收人不得写入仓库。

每次调度仍须显式提供单 URL 和发布者，不允许发现式爬取。若调度没有执行，下一次监控运行会把已到期但没有检查的来源标为漏检；但如果外部调度器从此永不调用本程序，本程序无法自行发出信号。这一外部活性边界必须由部署监控覆盖。

## 7. 提交前门禁

提交前流程必须验证最新运行并绑定 `run_id`、`run_snapshot_sha256` 及相关检查快照。当前正式输出契约尚未强制消费监控运行快照，因此 P2-05 保持 `FOUNDATION`；不得仅凭本监控器健康状态生成或标记 `SUBMISSION_CANDIDATE`。
