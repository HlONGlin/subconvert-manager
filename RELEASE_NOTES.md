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
