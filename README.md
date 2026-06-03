# FastAPI Image Upload Service

FastAPI service that accepts images through `multipart/form-data`, runs a local suspicious perturbation heuristic, extracts OCR text, and checks the image plus OCR text with Llama Guard 4 through OpenRouter.

## Moderation Pipeline

`POST /upload-image` runs the full pipeline:

1. Validate image.
2. Run local suspicious perturbation heuristic.
3. If suspicious perturbation-like patterns are found, reject immediately.
4. Run OCR with `easyocr`.
5. Send image and OCR text to Llama Guard 4 through OpenRouter.
6. If Llama Guard says unsafe or fails, reject.
7. Otherwise return success.

`POST /llama-guard/check-image` validates the image and sends it directly to Llama Guard 4 without the local heuristic or OCR pipeline.

## Important Limitation

The local suspicious perturbation detector is a heuristic. It is not proof of an adversarial attack. Without a target model, clean reference images, adversarial training data, or a trained detection model, the service can only report suspicious perturbation-like patterns.

## Local Heuristic Features

- Laplacian variance
- High-frequency residual energy
- Color channel inconsistency
- Local noise inconsistency
- JPEG blockiness awareness

High-frequency natural texture, text, compression artifacts, sharpening, or camera noise may affect the score and can produce false positives or false negatives.

## Installation

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Windows cmd:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment

Create an `.env` file from the example:

```bash
cp .env.example .env
```

Then set your OpenRouter API key:

```env
OPENROUTER_API_KEY=your_real_key_here
```

Default model:

```env
LLAMA_GUARD_MODEL=meta-llama/llama-guard-4-12b
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1/chat/completions
```

If OpenRouter uses a different model slug, update `LLAMA_GUARD_MODEL` in `.env`.

## Run

```bash
uvicorn app.main:app --reload
```

Docs:

```text
http://127.0.0.1:8000/docs
```

## Healthcheck

```bash
curl http://127.0.0.1:8000/
```

## Full Pipeline Upload

```bash
curl -X POST "http://127.0.0.1:8000/upload-image" \
  -F "file=@test.jpg"
```

## Direct Llama Guard Check

```bash
curl -X POST "http://127.0.0.1:8000/llama-guard/check-image" \
  -F "file=@test.jpg" \
  -F "ocr_text=optional text from image"
```

The OpenRouter request uses the OpenAI-compatible chat completions endpoint:

```text
https://openrouter.ai/api/v1/chat/completions
```

Optional OpenRouter ranking headers are sent when configured:

```text
HTTP-Referer
X-Title
```

## Run Tests

```bash
pytest
```

## Success Response Example

```json
{
  "status": "success",
  "reason": null,
  "message": "Image passed all checks and can be used.",
  "filename": "test.jpg",
  "content_type": "image/jpeg",
  "analysis": {
    "suspicious_perturbation": {
      "is_suspicious": false,
      "score": 0.21,
      "threshold": 0.65,
      "method": "multi_feature_perturbation_heuristic",
      "explanation": "No strong suspicious perturbation-like patterns were detected. This does not prove the image is clean; it only means the heuristic did not find strong indicators.",
      "features": {},
      "limitations": []
    },
    "ocr": {
      "has_text": true,
      "text": "Example text",
      "blocks": [
        {
          "text": "Example text",
          "confidence": 0.88
        }
      ],
      "error": null
    },
    "llama_guard": {
      "is_safe": true,
      "verdict": "safe",
      "raw_response": "safe",
      "reason": null,
      "provider": "openrouter",
      "model": "meta-llama/llama-guard-4-12b"
    }
  }
}
```

## Suspicious Perturbation Reject Example

```json
{
  "status": "rejected",
  "reason": "suspicious_perturbation_detected",
  "message": "Image rejected because suspicious perturbation-like patterns were detected.",
  "filename": "test.jpg",
  "content_type": "image/jpeg",
  "analysis": {
    "suspicious_perturbation": {
      "is_suspicious": true,
      "score": 0.78,
      "threshold": 0.65,
      "method": "multi_feature_perturbation_heuristic",
      "explanation": "Suspicious perturbation-like patterns were detected. This may indicate adversarial perturbations, but it can also be caused by compression artifacts, natural high-frequency texture, text, sharpening, or sensor noise.",
      "features": {},
      "limitations": []
    },
    "ocr": null,
    "llama_guard": null
  }
}
```

## Unsafe Llama Guard Reject Example

```json
{
  "status": "rejected",
  "reason": "unsafe_content_detected",
  "message": "Image rejected because Llama Guard classified it as unsafe.",
  "filename": "test.jpg",
  "content_type": "image/jpeg",
  "analysis": {
    "suspicious_perturbation": {},
    "ocr": {
      "has_text": false,
      "text": "",
      "blocks": [],
      "error": null
    },
    "llama_guard": {
      "is_safe": false,
      "verdict": "unsafe",
      "raw_response": "unsafe\nS1",
      "reason": "S1",
      "provider": "openrouter",
      "model": "meta-llama/llama-guard-4-12b"
    }
  }
}
```

## Llama Guard Error Reject Example

```json
{
  "status": "rejected",
  "reason": "llama_guard_failed",
  "message": "Image rejected because Llama Guard safety check failed.",
  "filename": "test.jpg",
  "content_type": "image/jpeg",
  "analysis": {
    "suspicious_perturbation": {},
    "ocr": {
      "has_text": false,
      "text": "",
      "blocks": [],
      "error": null
    },
    "llama_guard": {
      "is_safe": false,
      "verdict": "error",
      "raw_response": null,
      "reason": "Llama Guard check failed: OPENROUTER_API_KEY is not configured",
      "provider": "openrouter",
      "model": "meta-llama/llama-guard-4-12b"
    }
  }
}
```
