# 官方来源单文档冻结契约

## 目的

在案件数据保持本地的前提下，允许用户明确指定一个候选官方网站文档，通过受控 HTTPS GET 保存未经规范化的响应正文、必要响应元数据、TLS 对端证据和内容哈希，并支持完全离线重放校验。

这不是爬虫、站内搜索器或法律验证器。发布者主机登记见 [official-source-registry.json](official-source-registry.json)，结构见 [official-source-registry.schema.json](official-source-registry.schema.json) 和 [frozen-source-record.schema.json](frozen-source-record.schema.json)。

## 网络边界

- 每次 CLI 只接受一个用户明确提供的 URL；不发现链接、不批量翻页、不登录、不提交表单；
- 只允许注册表中的精确 HTTPS 主机和用途，不允许用户名、密码、片段或非 443 端口；
- 重定向最多三次，每一跳都重新执行同一发布者白名单检查；
- TLS 最低 1.2，使用系统信任库验证证书，并在发送 HTTP 请求前拒绝非公网对端 IP；
- 固定 `GET`、`Accept-Encoding: identity`、无 Cookie、无认证头；
- 总超时最多 60 秒，正文上限由注册表限制且不超过 25 MiB；
- 拒绝非 200、缺失/不允许的媒体类型、压缩/转换正文、声明长度错误或实际超限；
- 仅记录 Content-Type、Content-Length、Date、ETag 和 Last-Modified，不保存 Set-Cookie 等不必要响应头。

注册表的 `automated_access_authorization_status` 固定为 `NOT_ASSERTED`：精确官网和公开可访问不等于站点已授权自动化采集。当前能力只能用于低频、单文档、用户指定的只读冻结；批量案例采集必须另行满足来源政策、限速和停止条件。

## 不可变存储

响应正文按 SHA-256 保存为：

```text
objects/<hash前两位>/<完整hash>.bin
```

记录保存为 `records/<fetch_id>.json`，包含请求/最终 URL、选定响应头、每个网络跳的状态、TLS 版本、密码套件、对端 IP、对端证书 SHA-256、正文大小/哈希和 RFC 8785 记录快照。相同操作可幂等重放；同一路径内容冲突会阻断，不会覆盖。

只保存响应正文，不保存原始 HTTP framing；系统时钟也未认证。冻结字节可能是 HTML、PDF 或其他主动/恶意内容，后续只能由隔离解析器处理，不能执行宏、脚本或外链。

## 使用

在线冻结一个明确 URL：

```powershell
python scripts/fetch_official_source.py <https-url> `
  --publisher-code <registry-code> `
  --purpose NORMATIVE_LEGAL_SOURCE `
  --store <local-public-source-store>
```

离线重放：

```powershell
python scripts/validate_frozen_source.py <record.json> --store <local-public-source-store>
```

成功只证明保存的响应正文与记录中的哈希、路径和元数据一致。它不证明网站作者身份未被攻破、系统时钟准确、文档现行有效、条文适用、自动访问获得授权或材料可提交。规则与审查包在后续法律版本和审核门禁完成前仍保持未验证状态。
