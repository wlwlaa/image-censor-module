import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app


HMAC_SECRET = "hmac-secret-" + "x" * 32
DOWNLOAD_TOKEN = "download-token-" + "x" * 32
AUTH_HEADERS = {"Authorization": f"Bearer {DOWNLOAD_TOKEN}"}


def test_hash_mismatch_409(tmp_path: Path) -> None:
    client = TestClient(create_app(build_settings(tmp_path)))
    response = client.post("/v1/moderate", data={"prompt": "draw a safe corporate illustration"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"] == "ALLOW"

    artifact_id = payload["artifact_id"]
    release_path = tmp_path / "release" / f"{artifact_id}.png"
    release_path.write_bytes(b"tampered")

    download = client.get(f"/v1/download/{artifact_id}", headers=AUTH_HEADERS)
    assert download.status_code == 409
    assert download.json()["detail"] == "Artifact integrity verification failed"


def test_download_returns_verified_release(tmp_path: Path) -> None:
    client = TestClient(create_app(build_settings(tmp_path)))
    response = client.post("/v1/moderate", data={"prompt": "draw a safe corporate illustration"})
    artifact_id = response.json()["artifact_id"]
    download = client.get(f"/v1/download/{artifact_id}", headers=AUTH_HEADERS)
    assert download.status_code == 200
    assert download.headers["content-type"] == "image/png"


def test_download_requires_bearer_token(tmp_path: Path) -> None:
    client = TestClient(create_app(build_settings(tmp_path)))
    response = client.post("/v1/moderate", data={"prompt": "draw a safe corporate illustration"})
    artifact_id = response.json()["artifact_id"]
    download = client.get(f"/v1/download/{artifact_id}")
    assert download.status_code == 401
    assert download.headers["www-authenticate"] == "Bearer"


def test_moderate_blocks_unsafe_generated_filename(tmp_path: Path) -> None:
    client = TestClient(create_app(build_settings(tmp_path)))
    files = {"generated_image": ("unsafe-violence.png", png_bytes(), "image/png")}
    response = client.post("/v1/moderate", files=files)
    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"] == "BLOCK"
    assert "graphic_violence" in payload["categories"]
    assert not (tmp_path / "release" / f"{payload['artifact_id']}.png").exists()


def test_moderate_blocks_pii_before_mock_generation(tmp_path: Path) -> None:
    client = TestClient(create_app(build_settings(tmp_path)))
    files = {"input_image": ("passport.png", png_bytes(), "image/png")}
    response = client.post("/v1/moderate", files=files)
    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"] == "BLOCK"
    assert payload["artifact_id"] is None
    assert "pii_passport" in payload["categories"]


def test_moderate_fails_closed_on_detector_error(tmp_path: Path) -> None:
    client = TestClient(create_app(build_settings(tmp_path)))
    files = {"generated_image": ("detector_error.png", png_bytes(), "image/png")}
    response = client.post("/v1/moderate", files=files)
    payload = response.json()
    assert payload["verdict"] == "BLOCK"
    assert "internal_error" in payload["categories"]
    assert not (tmp_path / "release" / f"{payload['artifact_id']}.png").exists()


def test_mime_mismatch_rejected(tmp_path: Path) -> None:
    client = TestClient(create_app(build_settings(tmp_path)))
    files = {"generated_image": ("image.png", png_bytes(), "image/jpeg")}
    response = client.post("/v1/moderate", files=files)
    payload = response.json()
    assert payload["verdict"] == "BLOCK"
    assert "Declared MIME type does not match" in payload["errors"][0]


def build_settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, hmac_secret=HMAC_SECRET, download_token=DOWNLOAD_TOKEN)


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), color=(255, 255, 255)).save(output, format="PNG")
    return output.getvalue()
