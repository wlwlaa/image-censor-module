from app.policy_engine import PolicyEngine
from app.schemas import CheckResult, Severity, Verdict


def test_policy_engine_allows_only_clean_checks() -> None:
    decision = PolicyEngine().evaluate(
        [CheckResult(check="guard", verdict=Verdict.ALLOW, reason="passed")]
    )
    assert decision.verdict == Verdict.ALLOW


def test_policy_engine_blocks_on_error() -> None:
    decision = PolicyEngine().evaluate(
        [
            CheckResult(
                check="output_guard",
                verdict=Verdict.BLOCK,
                categories=["internal_error"],
                severity=Severity.CRITICAL,
                reason="failed",
                error="detector unavailable",
            )
        ]
    )
    assert decision.verdict == Verdict.BLOCK
    assert decision.categories == ["internal_error"]
    assert "Fail closed" in decision.reason


def test_policy_engine_prefers_block_over_review() -> None:
    decision = PolicyEngine().evaluate(
        [
            CheckResult(
                check="prompt_guard",
                verdict=Verdict.REVIEW,
                categories=["suspicious_bypass"],
                severity=Severity.MEDIUM,
                reason="review prompt",
            ),
            CheckResult(
                check="output_guard",
                verdict=Verdict.BLOCK,
                categories=["graphic_violence"],
                severity=Severity.HIGH,
                reason="block output",
            ),
        ]
    )
    assert decision.verdict == Verdict.BLOCK
    assert decision.severity == Severity.HIGH

