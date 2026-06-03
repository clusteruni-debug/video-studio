"""Bridge server tests."""

from worker.bridge.server import UI_DEV_CORS_ORIGINS, app


def test_bridge_cors_allows_configured_and_default_vite_dev_origins():
    assert "http://127.0.0.1:5160" in UI_DEV_CORS_ORIGINS
    assert "http://127.0.0.1:5173" in UI_DEV_CORS_ORIGINS
    assert "http://127.0.0.1:4160" in UI_DEV_CORS_ORIGINS

    response = app.test_client().get(
        "/api/health",
        headers={"Origin": "http://127.0.0.1:5173"},
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
