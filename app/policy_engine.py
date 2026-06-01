from __future__ import annotations

from app.schemas import CheckResult, PolicyDecision, SEVERITY_ORDER, Severity, Verdict


class PolicyEngine:
    version = "mvp-1"

    def evaluate(self, checks: list[CheckResult]) -> PolicyDecision:
        if not checks:
            return PolicyDecision(
                verdict=Verdict.BLOCK,
                categories=["internal_error"],
                severity=Severity.CRITICAL,
                reason="No security checks were executed",
            )

        categories = sorted({category for check in checks for category in check.categories})
        severity = max((check.severity for check in checks), key=SEVERITY_ORDER.get)

        failed = [check for check in checks if check.error]
        if failed:
            names = ", ".join(check.check for check in failed)
            return PolicyDecision(
                verdict=Verdict.BLOCK,
                categories=sorted(set(categories) | {"internal_error"}),
                severity=Severity.CRITICAL,
                reason=f"Fail closed: security check error in {names}",
            )

        blocked = [check for check in checks if check.verdict == Verdict.BLOCK]
        if blocked:
            return PolicyDecision(
                verdict=Verdict.BLOCK,
                categories=categories,
                severity=severity,
                reason="; ".join(check.reason for check in blocked),
            )

        review = [check for check in checks if check.verdict == Verdict.REVIEW]
        if review:
            return PolicyDecision(
                verdict=Verdict.REVIEW,
                categories=categories,
                severity=severity,
                reason="; ".join(check.reason for check in review),
            )

        return PolicyDecision(
            verdict=Verdict.ALLOW,
            categories=[],
            severity=Severity.NONE,
            reason="All mandatory checks passed",
        )

