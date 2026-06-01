from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_download_rejects_hash_mismatch(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path, hmac_secret="test-secret")))
    response = client.post("/v1/moderate", data={"prompt": "draw a safe corporate illustration"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"] == "ALLOW"

    artifact_id = payload["artifact_id"]
    release_path = tmp_path / "release" / f"{artifact_id}.png"
    release_path.write_bytes(b"tampered")

    download = client.get(f"/v1/download/{artifact_id}")
    assert download.status_code == 409
    assert download.json()["detail"] == "Artifact integrity verification failed"


def test_download_returns_verified_release(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path, hmac_secret="test-secret")))
    response = client.post("/v1/moderate", data={"prompt": "draw a safe corporate illustration"})
    artifact_id = response.json()["artifact_id"]
    download = client.get(f"/v1/download/{artifact_id}")
    assert download.status_code == 200
    assert download.headers["content-type"] == "image/png"


def test_moderate_blocks_unsafe_generated_filename(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path, hmac_secret="test-secret")))
    files = {"generated_image": ("unsafe-violence.png", _png_bytes(), "image/png")}
    response = client.post("/v1/moderate", files=files)
    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"] == "BLOCK"
    assert "graphic_violence" in payload["categories"]
    assert not (tmp_path / "release" / f"{payload['artifact_id']}.png").exists()


def test_moderate_blocks_pii_before_mock_generation(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path, hmac_secret="test-secret")))
    files = {"input_image": ("passport.png", _png_bytes(), "image/png")}
    response = client.post("/v1/moderate", files=files)
    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"] == "BLOCK"
    assert payload["artifact_id"] is None
    assert "pii_passport" in payload["categories"]


def test_moderate_fails_closed_on_detector_error(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path, hmac_secret="test-secret")))
    files = {"generated_image": ("detector_error.png", _png_bytes(), "image/png")}
    response = client.post("/v1/moderate", files=files)
    payload = response.json()
    assert payload["verdict"] == "BLOCK"
    assert "internal_error" in payload["categories"]
    assert not (tmp_path / "release" / f"{payload['artifact_id']}.png").exists()


def _png_bytes() -> bytes:
    import io

    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (8, 8), color=(255, 255, 255)).save(output, format="PNG")
    return output.getvalue()
