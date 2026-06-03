from app.services.llama_guard_service import (
    _build_chat_completions_url,
    parse_llama_guard_response,
)


def test_parse_safe() -> None:
    result = parse_llama_guard_response("safe")

    assert result["is_safe"] is True
    assert result["verdict"] == "safe"
    assert result["reason"] is None


def test_parse_safe_with_whitespace() -> None:
    result = parse_llama_guard_response("  safe\n")

    assert result["is_safe"] is True
    assert result["verdict"] == "safe"


def test_parse_unsafe() -> None:
    result = parse_llama_guard_response("unsafe")

    assert result["is_safe"] is False
    assert result["verdict"] == "unsafe"
    assert result["reason"] is None
    assert result["unsafe_reasons"] == []


def test_parse_unsafe_category() -> None:
    result = parse_llama_guard_response("unsafe\nS1")

    assert result["is_safe"] is False
    assert result["verdict"] == "unsafe"
    assert result["reason"] == "S1"
    assert result["unsafe_reasons"] == ["S1"]
    assert result["unsafe_reason_details"] == [
        {
            "code": "S1",
            "label": "Violent Crimes",
            "description": "Content related to planning, enabling, or committing violent crimes.",
        }
    ]


def test_parse_unsafe_reason() -> None:
    result = parse_llama_guard_response("unsafe\nViolence")

    assert result["is_safe"] is False
    assert result["verdict"] == "unsafe"
    assert result["reason"] == "Violence"
    assert result["unsafe_reasons"] == ["Violence"]
    assert result["unsafe_reason_details"][0]["code"] == "Violence"
    assert result["unsafe_reason_details"][0]["label"] == "Unmapped Llama Guard reason"


def test_parse_unsafe_multiple_reasons() -> None:
    result = parse_llama_guard_response("unsafe\nS1\nViolence")

    assert result["is_safe"] is False
    assert result["verdict"] == "unsafe"
    assert result["reason"] == "S1\nViolence"
    assert result["unsafe_reasons"] == ["S1", "Violence"]
    assert result["unsafe_reason_details"][0]["label"] == "Violent Crimes"
    assert result["unsafe_reason_details"][1]["label"] == "Unmapped Llama Guard reason"


def test_parse_privacy_category() -> None:
    result = parse_llama_guard_response("unsafe\nS7")

    assert result["is_safe"] is False
    assert result["unsafe_reason_details"] == [
        {
            "code": "S7",
            "label": "Privacy",
            "description": "Content that may expose sensitive personal information, private identifiers, credentials, or confidential data.",
        }
    ]


def test_parse_empty_response_rejects_by_default() -> None:
    result = parse_llama_guard_response("")

    assert result["is_safe"] is False
    assert result["verdict"] == "unknown"


def test_parse_weird_response_rejects_by_default() -> None:
    result = parse_llama_guard_response("I cannot classify this")

    assert result["is_safe"] is False
    assert result["verdict"] == "unknown"


def test_build_chat_completions_url_from_base_api_url() -> None:
    url = _build_chat_completions_url("https://openrouter.ai/api/v1")

    assert url == "https://openrouter.ai/api/v1/chat/completions"


def test_build_chat_completions_url_does_not_duplicate_path() -> None:
    url = _build_chat_completions_url(
        "https://openrouter.ai/api/v1/chat/completions"
    )

    assert url == "https://openrouter.ai/api/v1/chat/completions"
