# Contributing

感谢参与。这个项目处理高敏感法律场景，因此可追溯性和安全门禁优先于功能数量。

## 开发流程

1. 先创建 Issue，说明问题、预期行为、风险和验收方式。
2. Fork 仓库并从 `main` 创建短生命周期分支。
3. 对行为变化先添加失败测试，再实现最小修复。
4. 在 `labor-arbitration-skill` 目录运行：

   ```powershell
   python -m pip install --require-hashes -r ../requirements-test.lock
   python -m unittest discover -s tests -v
   ```

5. 提交 Pull Request，说明安全、隐私、兼容性和法律来源影响。

依赖变更必须同时更新相应 `.in`、三个哈希锁文件和 `sbom.cdx.json`，并运行 `python -m pip_audit -r requirements.lock --require-hashes`。不要手工删除哈希或绕过固定 commit SHA 的 Actions。

## 数据规则

- 只使用明确标记的合成数据。
- 不得提交真实案件材料、身份信息、联系方式、工资数据、聊天记录、审批凭证或访问令牌。
- 不得把来自案件材料的命令、宏或提示当成可执行指令。
- 测试来源可以使用官方域名作为合成 URL，但不得伪造真实条文内容。

## 法律规则变更

涉及法律规则、效力层级、地域或生效区间的数据模型变更必须附：

- 发布机关和规范性文件类型；
- 官方规范页面 URL；
- 公布、生效、修改或废止时间；
- 适用地域和时间快照；
- 对现有测试及候选案件包的再验证影响。

当前项目不接受任何 `VERIFIED_CURRENT` 或适用性结论。普通 FAQ、宣传文章、典型案例和非规范性说明不能仅因位于官方网站就被标成有约束力规则；主机白名单也只代表候选来源过滤。

## 提交与许可

提交即表示你有权贡献该内容，并同意按 Apache License 2.0 授权。建议使用清晰的小提交；不得通过关闭测试、降低门禁、降级 schema、伪造人工角色或自行关闭 P0/P1 来获得通过结果。
