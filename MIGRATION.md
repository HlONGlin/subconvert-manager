# 迁移说明（Migration）

本次升级为 **非破坏性改动**。

- 老版本 `data/sources.json` 中的订阅源没有 `clash_template` / `rate_limit_mbps` 字段：
  - 读取时会自动按默认值处理（模板默认 `simple`，限速默认 `0`）。
  - 保存/编辑后会自动写回新字段。

无需额外迁移步骤。
