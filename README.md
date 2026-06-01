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

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
export GENSECOPS_HMAC_SECRET="replace-with-a-random-secret"
uvicorn app.main:app --reload
```

Runtime storage is created automatically:

```text
data/quarantine/
data/release/
data/audit/audit.jsonl
```

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
curl -OJ http://127.0.0.1:8000/v1/download/<artifact_id>
```

Health check:

```bash
curl -sS http://127.0.0.1:8000/health
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
- Authentication, tenant isolation, KMS/HSM signing, malware scanning, and
  human review UI are production tasks.
