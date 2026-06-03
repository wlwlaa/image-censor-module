import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
import app.main as main_module
from app.main import create_app


HMAC_SECRET = "hmac-secret-" + "x" * 32
DOWNLOAD_TOKEN = "download-token-" + "x" * 32


class FailingAuditLogger:
    def append(self, event: dict) -> None:
        raise OSError("audit unavailable")


def test_secret_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GENSECOPS_HMAC_SECRET", raising=False)
    monkeypatch.setenv("GENSECOPS_DOWNLOAD_TOKEN", DOWNLOAD_TOKEN)
    with pytest.raises(ValueError, match="GENSECOPS_HMAC_SECRET"):
        Settings.from_env()


def test_download_token_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSECOPS_HMAC_SECRET", HMAC_SECRET)
    monkeypatch.delenv("GENSECOPS_DOWNLOAD_TOKEN", raising=False)
    with pytest.raises(ValueError, match="GENSECOPS_DOWNLOAD_TOKEN"):
        Settings.from_env()


def test_audit_failure_prevents_release(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, hmac_secret=HMAC_SECRET, download_token=DOWNLOAD_TOKEN)
    client = TestClient(create_app(settings, audit_logger=FailingAuditLogger()))
    response = client.post("/v1/moderate", data={"prompt": "draw a safe corporate illustration"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"] == "BLOCK"
    assert "release_pipeline" in payload["errors"][0]
    assert not list((tmp_path / "release").glob("*"))


def test_body_size_limit_returns_413(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        hmac_secret=HMAC_SECRET,
        download_token=DOWNLOAD_TOKEN,
        max_request_bytes=16,
    )
    client = TestClient(create_app(settings))
    response = client.post("/v1/moderate", data={"prompt": "this body is larger than sixteen bytes"})
    assert response.status_code == 413


def test_pre_generation_block_audit_contains_input_hash_and_versions(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, hmac_secret=HMAC_SECRET, download_token=DOWNLOAD_TOKEN)
    client = TestClient(create_app(settings))
    files = {"input_image": ("passport.png", png_bytes(), "image/png")}
    response = client.post("/v1/moderate", files=files)
    assert response.json()["verdict"] == "BLOCK"

    event = json.loads((tmp_path / "audit" / "audit.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert event["hashes"]["input_file_hash"]
    assert event["policy_version"] == "mvp-1"
    assert event["detector_versions"]["output_guard"] == "mock-1"


def test_demo_dataset_upload_rejects_path_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "demo_dataset_dir", lambda: tmp_path / "demo_dataset")
    settings = Settings(data_dir=tmp_path / "data", hmac_secret=HMAC_SECRET, download_token=DOWNLOAD_TOKEN)
    client = TestClient(create_app(settings))

    response = client.post(
        "/demo-dataset/upload",
        files=[("files", ("../manifest.json", b"[]", "application/json"))],
    )

    assert response.status_code == 400
    assert "inside demo_dataset" in response.json()["detail"]


def test_demo_dataset_upload_saves_manifest_and_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_dir = tmp_path / "demo_dataset"
    monkeypatch.setattr(main_module, "demo_dataset_dir", lambda: dataset_dir)
    settings = Settings(data_dir=tmp_path / "data", hmac_secret=HMAC_SECRET, download_token=DOWNLOAD_TOKEN)
    client = TestClient(create_app(settings))
    manifest = json.dumps(
        [
            {
                "id": "case-001",
                "title": "Custom safe",
                "input": "demo_dataset/input.png",
                "expected_decision": "ALLOW",
            }
        ]
    ).encode("utf-8")

    response = client.post(
        "/demo-dataset/upload",
        files=[
            ("files", ("custom/manifest.json", manifest, "application/json")),
            ("files", ("custom/input.png", png_bytes(), "image/png")),
        ],
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert (dataset_dir / "manifest.json").exists()
    assert (dataset_dir / "input.png").exists()


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), color=(255, 255, 255)).save(output, format="PNG")
    return output.getvalue()
