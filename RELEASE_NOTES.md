# v1.3.0

## Highlights

- Rebuild the whole UI: responsive source cards with status bars, traffic meters, status dots, and a dashboard summary row; no horizontal scrolling on phones.
- Turn subscription copying into format-labelled button groups; the button flips to "已复制 ✓" and the toast names the copied format.
- Add three source list layouts (list / card / compact) that are remembered per browser.
- Redesign the sidebar with inline SVG icons, clearer active state, quick-action group, and version info.
- Unify all form pages into grouped sections with validation styling, empty states, skeleton loading, focus rings, and reduced-motion support.
- Give every one of the ten themes text-safe ink tokens so all themes meet WCAG AA contrast, and switch to a system font stack with a clearer type scale.
- Add a site icon and consistent asset versioning across all nine pages.
- Add `one-click.sh`: interactive menu, guided admin account setup on first install, and `--update-only` for online updates; `quick-install.sh` becomes a compatibility shim.
- Fix popover menus that stayed open when clicking outside.

## Verification

- 89 unit tests pass; the sing-box integration tests are skipped unless `SINGBOX_BINARY` is configured.
- Playwright checks across 10 themes at 1440/1024/768/390 px: no horizontal overflow, no overlapping cells, no clipped text, WCAG AA contrast, and working copy / tab / theme / density / drawer interactions.

---

# v1.2.0

## Highlights

- Give each source and profile an independent subscription token and record access counts and last access times.
- Check sources in the background and display upstream traffic, expiry, reset information, and failure alerts.
- Add ten persistent themes with a visual theme gallery in settings.
- Adapt the source list to available screen width so its full information remains visible without horizontal scrolling at common desktop sizes.

## Verification

- 89 unit tests pass; one Mihomo integration test is skipped unless `MIHOMO_BINARY` is configured.
- sing-box 1.12.3 checks pass for Reality, VMess+WS+TLS, Trojan, SS2022, Hysteria2, TUIC, and WireGuard endpoint.

---

# v1.1.1

## Highlights

- Fix Reality uTLS fingerprints and migrate WireGuard to sing-box endpoints.
- Add complete sing-box configs with mixed inbound, DNS, selector/urltest groups, and bare outbound mode.
- Add an admin settings page, subscription backup import/export, dashboard summaries, and profile preview.
- Set subscription fetch cache TTL to 300 seconds by default.

## Verification

- 82 tests pass; one Mihomo integration test is skipped unless `MIHOMO_BINARY` is configured.
- sing-box 1.12.3 checks pass for Reality, VMess+WS+TLS, Trojan, SS2022, Hysteria2, TUIC, and WireGuard endpoint.

---

# v1.1.0

## Highlights

- Add combined subscriptions with source merging, keyword/regex filters, renaming, deduplication, sorting, and custom Clash templates.
- Add Clash, V2Ray, and sing-box outputs, plus source checks and recent status reporting.
- Detect subscription source types automatically and remember the selected home section.
- Remove the top security reminder and improve protocol conversion diagnostics and metadata.

## Verification

- 76 unit tests pass.
- Mihomo schema integration remains skipped unless `MIHOMO_BINARY` is configured.

---

# v1.0.2

## Highlights

- Preserve the existing deployment port when an update passes `INSTALL_PORT_OVERRIDE=auto`.
- Recover the previous port from an existing service definition when `config.env` is missing.

## Verification

- 63 unit tests pass.
- Mihomo schema integration remains skipped unless `MIHOMO_BINARY` is configured.

---

# v1.0.1

## Highlights

- Fix `v2ray_text` sources where escaped line breaks caused adjacent proxy URIs to be merged.
- Support literal `\\n`, `\\r\\n`, and HTML `<br>` separators.
- Add regression coverage for mixed VLESS and AnyTLS subscriptions.

## Verification

- 63 unit tests pass.
- Mihomo schema integration remains skipped unless `MIHOMO_BINARY` is configured.

---

# v1.0.0

## Highlights

- Preserve AnyTLS TLS parameters in Clash Play output.
- Reject unsupported AnyTLS Reality settings explicitly.
- Preserve explicit `udp=false` in VMess share-link conversion.
- Keep the configured port when updating an existing deployment.
- Add regression coverage for protocol round trips and installer behavior.

## Verification

- 62 unit tests pass.
- Mihomo schema integration is skipped unless `MIHOMO_BINARY` is configured.
