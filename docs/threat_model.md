# Threat Model

| Threat | MVP mitigation | Residual risk / production task |
|---|---|---|
| Direct provider output bypass | Release exists only after policy `ALLOW` | Isolate provider network and IAM |
| File replacement after approval | Download checks SHA-256 and passport HMAC | Use immutable object versions |
| Prompt bypass | Normalization and explicit rules | Add multilingual semantic model and output ensemble |
| PII sent to provider | Pre-generation PII adapter | Replace heuristics with OCR, DLP, document and QR detectors |
| Malformed or oversized image | Decode, format, byte and pixel limits | Run decoder in a sandbox |
| Detector failure | Policy engine fails closed | Add timeout, retries, metrics and bounded queues |
| Policy weakening | Version is recorded in passport | Policy-as-code, approval workflow and signed bundles |
| Audit tampering | Append-only local event stream | WORM storage and SIEM forwarding |
| IDOR on download | Artifact ID is random and release-only | Add authentication and tenant-bound authorization |
| Secret compromise | Secret stays outside repository | KMS/HSM, rotation and separation of duties |

