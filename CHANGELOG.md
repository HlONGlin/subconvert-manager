# 变更记录（Changelog）

## v1.0.1 - 2026-11-01

- [修复] `v2ray_text` 订阅源兼容字面量 `\\n`、`\\r\\n` 和 HTML `<br>` 分隔的多条 URI，避免后续节点被拼接到前一个节点名称。
- [新增] 增加 VLESS + AnyTLS 混合订阅的拆分回归测试。

## v1.0.0 - 2026-11-01

- [修复] AnyTLS 链接中的 `security=tls`、证书校验和客户端指纹正确转换到 Clash Play。
- [修复] VMess 显式 `udp=false` 在分享链接转换中丢失的问题。
- [修复] 拒绝不支持的 AnyTLS Reality 配置，避免生成不可用节点。
- [优化] 更新已有部署时保留 `config.env` 中的有效端口，不再因旧服务占用端口而随机替换。
- [新增] 版本标识与发布说明。

## 未发布

- [新增] 14 种协议的分享链接双向转换：VMess、VLESS、Trojan、SS、SSR、SOCKS5、HTTP/HTTPS、Hysteria 1/2、TUIC、AnyTLS、Mieru、WireGuard、SSH
- [增强] SS 插件及 SS2022、IPv6、特殊字符密码、Mieru 多端口、Hysteria2 端口跳跃、更多传输和 TLS 参数
- [修复] Trojan 省略 security 时默认 TLS，避免字符串 false 被当作真；坏节点隔离及节点重名处理
- [新增] 网页转换诊断、公私有订阅的跳过/警告数量响应头，未实现或不兼容设置明确提示
- [工程化] 协议编解码统一注册，增加完整转换、路由和鉴权回归测试与开发依赖说明
- [新增] ClashPlay 风格“部署型”Clash 输出模板（`template=play`）
- [新增] 订阅源维度的默认模板与限速字段：`clash_template` / `rate_limit_mbps`
- [新增] 全局异常处理与统一中文错误页（避免直接暴露 JSON/堆栈）
- [新增] 拉取订阅内容大小限制（默认 2MB，可通过 `MAX_REMOTE_BYTES` 配置）
- [增强] UI 统一视觉规范：卡片、表格、按钮、空态、复制、Toast
- [增强] 互转页新增模板选择与限速参数
- [增强] 安全提醒：默认口令/token 缺失会在首页提示
- [工程化] 增加基础单元测试（unittest），补齐文档说明

## 2026-02-17（fix2）
- [修复] 401 未认证提示中文化（缺少 Basic Auth 凭据时不再显示英文 Not authenticated）。
- [增强] 增加 /favicon.ico 空响应，避免浏览器反复 404 影响排障。
