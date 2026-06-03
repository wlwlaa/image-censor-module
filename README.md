# GenSecOps Psys Image Guardrail

Minimal FastAPI MVP for an independent image moderation gateway:

```text
request -> input checks -> mock generator or supplied output -> quarantine
        -> output guard -> deterministic policy -> release only on ALLOW
        -> verified download
```

The project intentionally has no heavy ML dependencies. `MockOutputDetector` is
a deterministic demo adapter. It blocks generated files whose filename or
metadata contains markers such as `unsafe`, `violence`, `gore`, or `pii`.

The MVP PII adapter scans filenames and metadata. It is not a production OCR
engine. See [architecture](docs/architecture.md) for the replacement points.

The optional API demo adds `/upload-image` and `/llama-guard/check-image` with
OCR, perturbation heuristics, and OpenRouter Llama Guard 4. Heavy ML packages
are isolated in `requirements-api-demo.txt`; the base demo starts without them.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
set -a
source .env
set +a
uvicorn app.main:create_app --factory --reload
```

The application fails during factory creation if either required secret is
missing or shorter than 32 characters.

`OPENROUTER_API_KEY` is optional for quick start. If it is missing, the Llama
Guard endpoint returns:

```json
{
  "status": "unavailable",
  "reason": "OPENROUTER_API_KEY is not configured"
}
```

Open the demo frontend:

```text
http://127.0.0.1:8000/
```

The `Demo token` field is required only for verified download. Enter the same
value that was exported as `GENSECOPS_DOWNLOAD_TOKEN`; the browser keeps it only
in the current page memory.

### Manual UI check

1. Open `http://127.0.0.1:8000/`.
2. Enter `${GENSECOPS_DOWNLOAD_TOKEN}` into `Demo token`.
3. Run `Safe image`: expect `ALLOW`, a Safety Passport, and a working Download.
4. Run `Unsafe output`: expect `BLOCK`.
5. Run `PII input`: expect a pre-generation `BLOCK` without an artifact ID.
6. Run `Detector failure`: expect fail-closed `BLOCK`.
7. Run `Tampered download`, modify the shown local release file, then press
   Download: expect `HTTP 409`.

## Public demo

```bash
./scripts/demo.sh
```

The script starts a local server when needed and demonstrates:

1. safe image `ALLOW` and verified download;
2. unsafe mock output `BLOCK`;
3. PII input `BLOCK` before release;
4. detector failure with fail-closed `BLOCK`;
5. tampered release rejected with HTTP `409`.

Run the demo against the local service: the final scenario intentionally
modifies a file in local release storage.

Presenter notes: [docs/demo_script.md](docs/demo_script.md).

Runtime storage is created automatically:

```text
data/quarantine/
data/release/
data/audit/audit.jsonl
```

## Local dataset auto demo

For defense, put your own `.png`, `.jpg`, or `.jpeg` files into
`demo_dataset/` and edit `demo_dataset/manifest.json`.

Each manifest item declares the files and expected decision:

```json
{
  "id": "case-001",
  "title": "Безопасное изображение",
  "input": "demo_dataset/case001_input.png",
  "generated": "demo_dataset/case001_generated.png",
  "expected_decision": "ALLOW",
  "description": "Безопасный кейс"
}
```

Use `expected_decision` as `ALLOW` or `BLOCK`. The backend reads only files
inside `demo_dataset/`; `../` and absolute paths are rejected.

On defense, open `/` and click `▶ Запустить автодемо` in the
`Автодемо по датасету` block. The run uses the same moderation logic as
`/v1/moderate` and shows expected vs actual decisions with PASS/FAIL summary.

The included images are synthetic placeholders only. The mock document is
explicitly marked `SYNTHETIC MOCK / NOT A REAL DOCUMENT`; it is not production
ML and contains no real passport, card, face, or PII data.

## API examples

Safe mock generation:

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/moderate \
  -F 'prompt=draw a safe corporate illustration'
```

Moderate an existing generated image:

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/moderate \
  -F 'prompt=check supplied generated output' \
  -F 'generated_image=@example.png;filename=unsafe-violence.png'
```

Check an img2img input before provider invocation:

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/moderate \
  -F 'input_image=@example.png;filename=passport.png'
```

Download an allowed artifact:

```bash
curl -OJ http://127.0.0.1:8000/v1/download/<artifact_id> \
  -H "Authorization: Bearer ${GENSECOPS_DOWNLOAD_TOKEN}"
```

Health check:

```bash
curl -sS http://127.0.0.1:8000/health
```

API demo image moderation:

```bash
curl -sS -X POST http://127.0.0.1:8000/upload-image \
  -F 'file=@example.jpg'
```

Direct Llama Guard image check:

```bash
curl -sS -X POST http://127.0.0.1:8000/llama-guard/check-image \
  -F 'file=@example.jpg'
```

Load local dataset manifest:

```bash
curl -sS http://127.0.0.1:8000/demo-dataset
```

Run local dataset auto demo:

```bash
curl -sS -X POST http://127.0.0.1:8000/demo-dataset/run
```

## Full API demo mode

Install optional OCR and perturbation detector dependencies:

```bash
pip install -r requirements.txt -r requirements-api-demo.txt
```

Set OpenRouter variables in `.env`:

```bash
OPENROUTER_API_KEY=<your-key>
LLAMA_GUARD_MODEL=meta-llama/llama-guard-4-12b
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1/chat/completions
OPENROUTER_SITE_URL=
OPENROUTER_APP_NAME=GenSecOps API Demo
LLAMA_GUARD_TIMEOUT_SECONDS=30
```

## Test

```bash
pytest
```

## MVP limitations

- No ShieldGemma integration is claimed or implemented.
- OCR is an adapter with filename and metadata heuristics only.
- Local filesystem storage demonstrates enforcement but is not production
  object storage.
- Audit is append-only JSONL, not WORM storage.
- Download authorization uses one environment-provided bearer token for the
  demo. Per-user authorization and tenant isolation are roadmap tasks.
- HMAC signing uses an environment-provided secret. KMS/HSM signing and key
  rotation are roadmap tasks.
- Request body size is bounded by `Content-Length`; a production reverse proxy
  must also enforce its own body limit.
- Malware scanning and human review UI are roadmap tasks.

## Required environment variables

| Variable | Purpose |
|---|---|
| `GENSECOPS_HMAC_SECRET` | HMAC signing secret, at least 32 characters |
| `GENSECOPS_DOWNLOAD_TOKEN` | Demo download bearer token, at least 32 characters |
| `GENSECOPS_DATA_DIR` | Runtime storage root, default `data` |
| `GENSECOPS_MAX_UPLOAD_BYTES` | Per-file upload limit |
| `GENSECOPS_MAX_REQUEST_BYTES` | Multipart request body limit |
| `GENSECOPS_MAX_PIXELS` | Decoded image pixel limit |
| `OPENROUTER_API_KEY` | Optional OpenRouter API key for `/llama-guard/check-image` |
| `LLAMA_GUARD_MODEL` | Optional model name, default `meta-llama/llama-guard-4-12b` |
| `OPENROUTER_BASE_URL` | Optional OpenRouter chat completions URL |
| `OPENROUTER_SITE_URL` | Optional OpenRouter referer metadata |
| `OPENROUTER_APP_NAME` | Optional OpenRouter app title metadata |
| `LLAMA_GUARD_TIMEOUT_SECONDS` | Optional Llama Guard request timeout |

## Implemented vs roadmap

Implemented:

- prompt rules and Unicode normalization;
- input and output image validation with MIME consistency checks;
- quarantine and release directories;
- deterministic policy checks;
- HMAC passport bound to artifact ID;
- bearer-protected download with hash and signature verification;
- audit-before-release flow.

Roadmap:

- validated ShieldGemma adapter;
- production OCR, DLP, barcode and malware detectors;
- private object storage with separate IAM roles;
- tenant-aware authorization, KMS/HSM, WORM audit and SIEM forwarding.

Detailed scope: [docs/implemented_vs_roadmap.md](docs/implemented_vs_roadmap.md).
Security review summary: [docs/security_review_summary.md](docs/security_review_summary.md).
