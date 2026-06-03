import base64
from typing import Any

import httpx

from app.config import settings


PROVIDER = "openrouter"
CHAT_COMPLETIONS_PATH = "/chat/completions"
DEFAULT_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
LLAMA_GUARD_SAFETY_CATEGORIES = {
    "S1": {
        "label": "Violent Crimes",
        "description": "Content related to planning, enabling, or committing violent crimes.",
    },
    "S2": {
        "label": "Non-Violent Crimes",
        "description": "Content related to non-violent wrongdoing, fraud, theft, or other criminal activity.",
    },
    "S3": {
        "label": "Sex-Related Crimes",
        "description": "Content related to sexual crimes or non-consensual sexual activity.",
    },
    "S4": {
        "label": "Child Sexual Exploitation",
        "description": "Content involving sexual exploitation or sexualization of minors.",
    },
    "S5": {
        "label": "Defamation",
        "description": "Content that may contain defamatory claims about a person or entity.",
    },
    "S6": {
        "label": "Specialized Advice",
        "description": "Content that may request or provide high-impact professional advice such as medical, legal, or financial guidance.",
    },
    "S7": {
        "label": "Privacy",
        "description": "Content that may expose sensitive personal information, private identifiers, credentials, or confidential data.",
    },
    "S8": {
        "label": "Intellectual Property",
        "description": "Content that may involve copyrighted, trademarked, or otherwise protected intellectual property.",
    },
    "S9": {
        "label": "Indiscriminate Weapons",
        "description": "Content related to weapons that can cause mass or indiscriminate harm.",
    },
    "S10": {
        "label": "Hate",
        "description": "Content that may attack or demean protected classes or promote hateful conduct.",
    },
    "S11": {
        "label": "Suicide & Self-Harm",
        "description": "Content related to suicide, self-harm, or instructions that could facilitate self-injury.",
    },
    "S12": {
        "label": "Sexual Content",
        "description": "Sexual, explicit, or adult content.",
    },
    "S13": {
        "label": "Elections",
        "description": "Content related to elections, voting, political persuasion, or election integrity.",
    },
    "S14": {
        "label": "Code Interpreter Abuse",
        "description": "Text-only content related to abusing code execution, automation, or interpreter capabilities.",
    },
}


def _build_chat_completions_url(base_url: str) -> str:
    normalized_url = base_url.rstrip("/")

    if normalized_url.endswith(CHAT_COMPLETIONS_PATH):
        return normalized_url

    return f"{normalized_url}{CHAT_COMPLETIONS_PATH}"


def _explain_unsafe_reason(reason: str) -> dict[str, str]:
    normalized_reason = reason.strip()
    category = LLAMA_GUARD_SAFETY_CATEGORIES.get(normalized_reason.upper())

    if category:
        return {
            "code": normalized_reason.upper(),
            "label": category["label"],
            "description": category["description"],
        }

    return {
        "code": normalized_reason,
        "label": "Unmapped Llama Guard reason",
        "description": "Llama Guard returned this reason, but it is not a known S-code in the local category mapping.",
    }


def explain_unsafe_reasons(reasons: list[str]) -> list[dict[str, str]]:
    return [_explain_unsafe_reason(reason) for reason in reasons]


def parse_llama_guard_response(raw_text: str) -> dict[str, Any]:
    raw_response = (raw_text or "").strip()
    model = settings.llama_guard_model

    if not raw_response:
        return {
            "is_safe": False,
            "verdict": "unknown",
            "raw_response": raw_response,
            "reason": "Unable to parse Llama Guard response. Rejected by default.",
            "provider": PROVIDER,
            "model": model,
        }

    lines = raw_response.splitlines()
    first_line = lines[0].strip().lower()
    unsafe_reasons = [line.strip() for line in lines[1:] if line.strip()]
    reason = "\n".join(unsafe_reasons) or None

    if first_line.startswith("unsafe"):
        return {
            "is_safe": False,
            "verdict": "unsafe",
            "raw_response": raw_response,
            "reason": reason,
            "unsafe_reasons": unsafe_reasons,
            "unsafe_reason_details": explain_unsafe_reasons(unsafe_reasons),
            "provider": PROVIDER,
            "model": model,
        }

    if first_line.startswith("safe"):
        return {
            "is_safe": True,
            "verdict": "safe",
            "raw_response": raw_response,
            "reason": None,
            "provider": PROVIDER,
            "model": model,
        }

    return {
        "is_safe": False,
        "verdict": "unknown",
        "raw_response": raw_response,
        "reason": "Unable to parse Llama Guard response. Rejected by default.",
        "provider": PROVIDER,
        "model": model,
    }


def _failure_result(error: str) -> dict[str, Any]:
    return {
        "is_safe": False,
        "verdict": "error",
        "raw_response": None,
        "reason": f"Llama Guard check failed: {error}",
        "provider": PROVIDER,
        "model": settings.llama_guard_model,
    }


def _format_http_error(response: httpx.Response) -> str:
    response_text = response.text.strip()
    if not response_text:
        response_text = "<empty response body>"

    return (
        f"OpenRouter returned HTTP {response.status_code} for {response.url}. "
        f"Response body: {response_text}"
    )


async def check_image_with_llama_guard(
    image_bytes: bytes,
    mime_type: str,
    ocr_text: str | None = None,
) -> dict[str, Any]:
    if not settings.openrouter_api_key:
        return _failure_result("OPENROUTER_API_KEY is not configured")

    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{base64_image}"
    url = _build_chat_completions_url(settings.openrouter_base_url)

    payload = {
        "model": settings.llama_guard_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "You are a strict multimodal safety classifier. "
                            "Classify whether the provided image and OCR text are safe or unsafe. Make sure to reject all political signs, including flags and other symbols, as well as any content that may be NSFW, violent, hateful, or otherwise unsafe."
                            "Return only one of the following formats:\n"
                            "safe\n"
                            "or\n"
                            "unsafe\n<short reason>"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": data_url,
                        },
                    },
                    {
                        "type": "text",
                        "text": f"OCR text extracted from the image: {ocr_text or ''}",
                    },
                ],
            }
        ],
        "temperature": 0,
    }

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }

    if settings.openrouter_site_url:
        headers["HTTP-Referer"] = settings.openrouter_site_url
    if settings.openrouter_app_name:
        headers["X-Title"] = settings.openrouter_app_name

    try:
        async with httpx.AsyncClient(timeout=settings.llama_guard_timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.is_error:
                return _failure_result(_format_http_error(response))
            response_data = response.json()

        raw_text = response_data["choices"][0]["message"]["content"]
        return parse_llama_guard_response(str(raw_text))
    except Exception as exc:
        return _failure_result(str(exc))
