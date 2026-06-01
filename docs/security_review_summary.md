# Security Review Summary

## Fixed Issues

| Issue | Fix |
|---|---|
| Random HMAC fallback invalidated passports after restart | Explicit HMAC secret is required and must be at least 32 characters |
| Download treated UUID as an access control | Demo bearer token is required |
| Passport was not bound to requested artifact ID | Verification compares expected and signed artifact IDs |
| Policy could allow an incomplete set of checks | Mandatory input and output stages are enforced |
| Release could exist before decision audit | Decision audit is written before promotion |
| Promotion copied files directly | Temp-file promotion and rename are used; failures revoke release artifacts |
| MIME spoofing was accepted | MIME is required and must match detected image format |
| Audit lacked decision context | Versions, passport digest, input hash, and download request IDs are recorded |
| Multipart body had no application-level cap | `Content-Length` middleware returns `413` above the configured limit |

## Residual Risks

| Risk | MVP status | Production action |
|---|---|---|
| Single download bearer token | Accepted for local demo only | Add user and tenant authorization |
| Local filesystem access | Processes with host access remain trusted | Use isolated object storage and IAM |
| HMAC secret in environment | Accepted for MVP | Use KMS/HSM and rotation |
| PII quality | Filename and metadata heuristics only | Add validated OCR and DLP |
| Image safety quality | Mock detector only | Integrate and evaluate a real detector adapter |
| Decoder isolation | Pillow runs in the application process | Add sandboxing and malware scanning |
| Audit durability | Append-only local JSONL | Add WORM storage and SIEM |
| Body limit | Depends on `Content-Length` | Enforce limit in reverse proxy as well |

## Demo Security Claim

The MVP demonstrates an enforcement path, not a production moderation model:

```text
quarantine -> mandatory checks -> deterministic policy -> audited release
           -> signed passport -> authorized verified download
```

