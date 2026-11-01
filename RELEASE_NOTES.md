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
