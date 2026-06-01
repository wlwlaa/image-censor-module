# Public Demo Script

Target duration: 3–5 minutes.

## Preparation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./scripts/demo.sh
```

The script starts a local FastAPI server if `/health` is not already available.
It creates a temporary valid PNG and runs five deterministic scenarios.
Run it against the local service because the final scenario intentionally
modifies local release storage.

## Presenter Flow

### 1. Safe image: ALLOW and verified download

Say:

> The generator is not allowed to return bytes directly to the user. The result
> enters quarantine, passes mandatory output checks, receives a signed safety
> passport, and is copied to release storage. Download verifies authorization,
> artifact binding, HMAC, and hash.

Expected API result:

```json
{"verdict":"ALLOW","artifact_id":"...","passport":{"verdict":"ALLOW","sha256":"..."}}
```

Expected download status: `HTTP 200`.

Demonstrated property: release exists only after `ALLOW`; download verifies the
released artifact.

### 2. Unsafe mock output: BLOCK

Say:

> A supplied generated image is deliberately marked as unsafe. It still reaches
> quarantine first, but the output detector blocks it. No release artifact is
> created.

Expected API result:

```json
{"verdict":"BLOCK","categories":["graphic_violence","unsafe_content"]}
```

Demonstrated property: generator output is untrusted and moderated independently.

### 3. PII input: BLOCK before release

Say:

> For img2img, sensitive input must be blocked before a provider call. The MVP
> adapter uses deterministic filename and metadata heuristics. Production OCR
> and DLP are roadmap items.

Expected API result:

```json
{"verdict":"BLOCK","categories":["payment_details","pii_passport"],"artifact_id":null}
```

Demonstrated property: pre-generation PII gate prevents provider exposure.

### 4. Detector failure: fail closed

Say:

> A failed security adapter must never degrade into an allow decision. This
> scenario simulates detector failure.

Expected API result:

```json
{"verdict":"BLOCK","categories":["internal_error"]}
```

Demonstrated property: detector errors fail closed.

### 5. Tampered release: download returns 409

Say:

> We modify the released bytes after approval. Download recomputes SHA-256 and
> validates the signed passport. The altered object is rejected.

Expected result:

```json
{"detail":"Artifact integrity verification failed"}
```

Expected status: `HTTP 409`.

Demonstrated property: post-approval file replacement is detected.

## Closing Statement

> This MVP does not claim production-grade image classification. It proves the
> enforcement path: quarantine, mandatory checks, deterministic policy, audited
> release, signed passport, authorized verified download, and fail-closed errors.
