# Release Checklist

- [ ] `VERSION` 与 `CHANGELOG.md` 一致。
- [ ] 完整单元测试和 Python 编译检查通过。
- [ ] Draft 2020-12 Schema 元校验与完整 v1.2 样本校验通过。
- [ ] Skill 官方结构验证通过。
- [ ] CI、CodeQL 和依赖审查通过。
- [ ] 未提交 `__pycache__`、真实案件数据、密钥、令牌或审批凭证。
- [ ] 法律规则相关变更仍保持 `UNVERIFIED_CANDIDATE`，没有伪造来源现行性或适用性。
- [ ] 非空 P0/P1 发现保持阻断；本地 JSON 不得关闭风险。
- [ ] 能力矩阵、验证报告的 verified/not_verified 与实现一致。
- [ ] 扫描器竞态、链接/重解析点、资源上限和原子输出回归测试通过。
- [ ] README、可靠性契约、威胁模型和安全政策与行为一致。
- [ ] 发布标签使用 `vMAJOR.MINOR.PATCH`，发布说明列出兼容性和残余风险。
