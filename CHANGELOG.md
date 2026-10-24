# 变更记录（Changelog）

## 未发布

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
