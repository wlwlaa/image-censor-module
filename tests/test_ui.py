from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_ui_page_loads() -> None:
    response = client.get("/ui")

    assert response.status_code == 200
    assert "Шлюз безопасности изображений" in response.text
    assert "Альфа-Банк" in response.text
    assert "/static/css/styles.css" in response.text
    assert "/static/js/app.js" in response.text


def test_static_assets_load() -> None:
    css_response = client.get("/static/css/styles.css")
    js_response = client.get("/static/js/app.js")

    assert css_response.status_code == 200
    assert js_response.status_code == 200
    assert "--red-700" in css_response.text
    assert "Run full safety check" not in js_response.text
