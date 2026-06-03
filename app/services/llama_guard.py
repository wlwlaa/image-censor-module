from __future__ import annotations

import base64
from typing import Any

from app.config import ApiDemoSettings


PROVIDER = "openrouter"
CHAT_COMPLETIONS_PATH = "/chat/completions"
LLAMA_GUARD_SAFETY_CATEGORIES = {
    "S1": "Violent Crimes",
    "S2": "Non-Violent Crimes",
    "S3": "Sex-Related Crimes",
    "S4": "Child Sexual Exploitation",
    "S5": "Defamation",
    "S6": "Specialized Advice",
    "S7": "Privacy",
    "S8": "Intellectual Property",
    "S9": "Indiscriminate Weapons",
    "S10": "Hate",
    "S11": "Suicide & Self-Harm",
    "S12": "Sexual Content",
    "S13": "Elections",
    "S14": "Code Interpreter Abuse",
}


def _build_chat_completions_url(base_url: str) -> str:
    normalized_url = base_url.rstrip("/")
    if normalized_url.endswith(CHAT_COMPLETIONS_PATH):
        return normalized_url
    return f"{normalized_url}{CHAT_COMPLETIONS_PATH}"


def explain_unsafe_reasons(reasons: list[str]) -> list[dict[str, str]]:
    details = []
    for reason in reasons:
        code = reason.strip().upper()
        details.append(
            {
                "code": code,
                "label": LLAMA_GUARD_SAFETY_CATEGORIES.get(code, "Unmapped Llama Guard reason"),
            }
        )
    return details


def parse_llama_guard_response(raw_text: str, model: str | None = None) -> dict[str, Any]:
    raw_response = (raw_text or "").strip()
    model_name = model or ApiDemoSettings.from_env().llama_guard_model

    if not raw_response:
        return _result(
            verdict="unknown",
            is_safe=False,
            reason="Unable to parse Llama Guard response. Rejected by default.",
            model=model_name,
            raw_response=raw_response,
        )

    lines = raw_response.splitlines()
    first_line = lines[0].strip().lower()
    unsafe_reasons = [line.strip() for line in lines[1:] if line.strip()]
    reason = "\n".join(unsafe_reasons) or None

    if first_line.startswith("unsafe"):
        return _result(
            verdict="unsafe",
            is_safe=False,
            reason=reason,
            model=model_name,
            raw_response=raw_response,
            unsafe_reasons=unsafe_reasons,
            unsafe_reason_details=explain_unsafe_reasons(unsafe_reasons),
        )
    if first_line.startswith("safe"):
        return _result(verdict="safe", is_safe=True, reason=None, model=model_name, raw_response=raw_response)

    return _result(
        verdict="unknown",
        is_safe=False,
        reason="Unable to parse Llama Guard response. Rejected by default.",
        model=model_name,
        raw_response=raw_response,
    )


def _result(
    *,
    verdict: str,
    is_safe: bool,
    reason: str | None,
    model: str,
    raw_response: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "is_safe": is_safe,
        "verdict": verdict,
        "raw_response": raw_response,
        "reason": reason,
        "provider": PROVIDER,
        "model": model,
        **extra,
    }


def unavailable_result(reason: str, settings: ApiDemoSettings | None = None) -> dict[str, Any]:
    config = settings or ApiDemoSettings.from_env()
    return _result(verdict="unavailable", is_safe=False, reason=reason, model=config.llama_guard_model)


def _failure_result(error: str, settings: ApiDemoSettings) -> dict[str, Any]:
    return _result(
        verdict="error",
        is_safe=False,
        reason=f"Llama Guard check failed: {error}",
        model=settings.llama_guard_model,
    )


def _format_http_error(response: Any) -> str:
    response_text = response.text.strip() or "<empty response body>"
    return f"OpenRouter returned HTTP {response.status_code} for {response.url}. Response body: {response_text}"


async def check_image_with_llama_guard(
    image_bytes: bytes,
    mime_type: str,
    ocr_text: str | None = None,
    settings: ApiDemoSettings | None = None,
) -> dict[str, Any]:
    config = settings or ApiDemoSettings.from_env()
    if not config.openrouter_api_key:
        return unavailable_result("OPENROUTER_API_KEY is not configured", config)

    try:
        import httpx
    except ImportError:
        return unavailable_result("httpx is not installed; install requirements-api-demo.txt", config)

    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{base64_image}"
    payload = {
        "model": config.llama_guard_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "You are a strict multimodal safety classifier. Classify whether the "
                            "provided image and OCR text are safe or unsafe. Return only:\n"
                            "safe\nor\nunsafe\n<short reason>"
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": f"OCR text extracted from the image: {ocr_text or ''}"},
                ],
            }
        ],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {config.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    if config.openrouter_site_url:
        headers["HTTP-Referer"] = config.openrouter_site_url
    if config.openrouter_app_name:
        headers["X-Title"] = config.openrouter_app_name

    try:
        async with httpx.AsyncClient(timeout=config.llama_guard_timeout_seconds) as client:
            response = await client.post(_build_chat_completions_url(config.openrouter_base_url), headers=headers, json=payload)
            if response.is_error:
                return _failure_result(_format_http_error(response), config)
            response_data = response.json()
        raw_text = response_data["choices"][0]["message"]["content"]
        return parse_llama_guard_response(str(raw_text), model=config.llama_guard_model)
    except Exception as exc:
        return _failure_result(str(exc), config)
