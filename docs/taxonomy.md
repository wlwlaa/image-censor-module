# MVP Taxonomy

| Category | Trigger in MVP | Decision |
|---|---|---|
| `sexual_content` | Forbidden prompt marker | `BLOCK` |
| `graphic_violence` | Prompt or output filename/metadata marker | `BLOCK` |
| `unsafe_content` | Output filename/metadata marker | `BLOCK` |
| `pii` | Output filename/metadata marker | `BLOCK` |
| `pii_passport` | Input filename/metadata marker | `BLOCK` |
| `payment_details` | Payment marker or Luhn-valid card-like number | `BLOCK` |
| `qr_or_barcode` | QR or barcode marker | `BLOCK` |
| `fraud_document` | Forbidden prompt marker | `BLOCK` |
| `phishing_asset` | Forbidden prompt marker | `BLOCK` |
| `suspicious_bypass` | Bypass rule | `REVIEW` |
| `internal_error` | Mandatory guard failure | `BLOCK` |

The MVP taxonomy is intentionally small. It demonstrates deterministic policy
enforcement. Production detectors require a separately approved taxonomy,
calibrated thresholds, and category-level evaluation.

