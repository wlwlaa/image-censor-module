from app.passport import PassportService
from app.schemas import Verdict


def test_passport_verifies_original_content() -> None:
    service = PassportService("test-secret")
    passport = service.issue(
        artifact_id="a" * 32,
        content=b"original",
        policy_version="test-policy",
        detector_versions={"mock": "1"},
        verdict=Verdict.ALLOW,
    )
    assert service.verify(passport, b"original")


def test_passport_rejects_tampered_content() -> None:
    service = PassportService("test-secret")
    passport = service.issue(
        artifact_id="a" * 32,
        content=b"original",
        policy_version="test-policy",
        detector_versions={"mock": "1"},
        verdict=Verdict.ALLOW,
    )
    assert not service.verify(passport, b"tampered")

