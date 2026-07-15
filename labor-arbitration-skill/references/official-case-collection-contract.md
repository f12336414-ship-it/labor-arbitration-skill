# 官方公开案例受控采集契约

## 范围

本采集器只处理用户明确提供的单个官方公开案例 URL。它不搜索、不遍历列表、不批量翻页、不登录、不绕过验证码或访问控制，也不把公开可访问等同于允许自动采集或再次传播。

采集分三层：

1. [官方来源注册表](official-source-registry.json)必须允许发布者使用 `OFFICIAL_CASE` 用途；
2. `fetch_official_case.py` 在共享本地账本中先登记发布者限速，再调用单文档 HTTPS 冻结器；
3. `build_official_case_record.py` 只生成受控分类元数据，不复制案件正文、当事人姓名或裁判结论。

## 使用

```powershell
python scripts/fetch_official_case.py <明确URL> `
  --publisher-code <code> `
  --store <本地公开来源存储> `
  --rate-limit-ledger <共享限速账本目录>

python scripts/build_official_case_record.py <冻结记录.json> `
  --store <本地公开来源存储> `
  --category WAGE_OR_WAGE_DIFFERENCE `
  --document-type PUBLIC_JUDGMENT `
  --procedural-stage SECOND_INSTANCE `
  --jurisdiction-scope NATIONAL

python scripts/validate_official_case_record.py <案例分类记录.json>
```

同一发布者的两个采集预留必须满足注册表中的最小间隔。账本使用跨进程排他锁、系统时钟回退阻断和 RFC 8785 自快照；它只约束使用同一账本的本项目客户端，不能证明其他客户端也被限速。

## 隐私和复用

公开页面仍可能包含个人信息、未充分匿名内容或受限制的再利用材料。因此分类记录固定：

- `privacy_review_status: REQUIRED_BEFORE_ANY_REDISSEMINATION`；
- `redistribution_status: BLOCKED`；
- `classification_status: UNVERIFIED_MANUAL_CLASSIFICATION`。

未经来源政策和隐私审核，冻结正文不得进入 GitHub、Issue、PR、CI、公开数据集或外部模型。公开案例可以作为分层评测来源，但不能替代含原始证据、过程材料和授权依据的完整真实案件。
