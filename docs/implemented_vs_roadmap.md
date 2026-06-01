# Implemented vs Roadmap

## Implemented in MVP

| Area | Implementation |
|---|---|
| API | FastAPI moderation, download, and health endpoints |
| Prompt Guard | Unicode normalization and explainable keyword/bypass rules |
| Input Validation | Byte limit, MIME consistency, decoded format, pixel limit, metadata stripping |
| PII Gate | Deterministic filename and metadata heuristics |
| Output Guard | Adapter protocol and deterministic mock detector |
| Policy | Mandatory checks and fail-closed `ALLOW / REVIEW / BLOCK` decisions |
| Storage | Local quarantine and release directories |
| Release | Audit-before-release and temp-file promotion |
| Passport | Artifact ID, SHA-256, policy version, detector versions, timestamp, HMAC |
| Download | Demo bearer token, artifact binding, hash and HMAC verification |
| Audit | Append-only JSONL with request IDs, hashes, versions, checks, verdicts, and errors |

## Production Roadmap

| Area | Production replacement |
|---|---|
| Output classifier | Separately evaluated model adapter; no model is claimed in MVP |
| OCR / PII | Sandboxed OCR, DLP, document and QR/barcode detectors |
| Storage | Private object storage, distinct IAM roles, TTL, immutable versions |
| Signing | KMS/HSM, key IDs, rotation, separation of duties |
| Authorization | Per-user and tenant-bound access control |
| Audit | WORM sink and SIEM forwarding |
| Parsing | Sandboxed decoder and malware scanning |
| Operations | Metrics, bounded queues, review workflow, load and adversarial tests |

## Honest Limitations

- The mock detector proves integration behavior, not ML quality.
- PII heuristics do not inspect visible pixels.
- One demo download token is not tenant authorization.
- Local directories do not enforce production IAM boundaries.
- HMAC environment secrets are not KMS/HSM-backed.
- `Content-Length` middleware must be complemented by a reverse proxy body limit.

