"""Zero-paid policy tests for Video Studio provider routing."""

import json
from pathlib import Path

from worker.bridge import image_router
from worker.media.model_router import ProviderAvailability, choose_route
from worker.media.provider_policy import (
    allowed_preference,
    is_paid_provider,
    paid_providers_allowed,
)
from worker.planner.sample_plan import SceneSpec


def _disable_paid(monkeypatch):
    monkeypatch.delenv("VIDEO_STUDIO_ALLOW_PAID", raising=False)
    monkeypatch.delenv("VIDEO_STUDIO_ALLOW_PAID_PROVIDERS", raising=False)


def test_paid_providers_disabled_by_default(monkeypatch):
    _disable_paid(monkeypatch)

    assert not paid_providers_allowed()
    assert is_paid_provider("imagen")
    assert is_paid_provider("veo3")
    assert "imagen" not in allowed_preference("image")
    assert "veo3" not in allowed_preference("video")
    assert "runway" not in allowed_preference("video")


def test_paid_providers_require_explicit_opt_in(monkeypatch):
    _disable_paid(monkeypatch)
    monkeypatch.setenv("VIDEO_STUDIO_ALLOW_PAID_PROVIDERS", "1")

    assert paid_providers_allowed()
    assert "imagen" in allowed_preference("image")
    assert "veo3" in allowed_preference("video")


def test_zero_paid_policy_forces_premium_route_local(monkeypatch):
    _disable_paid(monkeypatch)
    scene = SceneSpec(
        id="scene-01",
        title="Hero",
        prompt="cinematic opening shot",
        durationSec=5.0,
        priority=5,
        humanRealism=5,
        nativeAudioNeed=5,
        canUseStillImage=False,
        subtitleText="Hero line",
        routeHint="local",
    )

    decision = choose_route(
        scene,
        budget_mode="premium",
        availability=ProviderAvailability(veo3=True, premium_enabled=True),
    )

    assert decision.route == "local"
    assert decision.estimatedCostUsd == 0.0
    assert "zero-paid" in decision.reason


def test_default_image_route_skips_billable_search_and_imagen(monkeypatch):
    _disable_paid(monkeypatch)
    calls: list[str] = []

    def fake_serper(query: str) -> str:
        calls.append("serper")
        return "https://serper.example/image.jpg"

    def fake_flash(prompt: str, output_dir: str | None = None) -> str:
        calls.append("gemini-flash")
        return "storage/cache/free.png"

    def fake_imagen(
        prompt: str,
        output_dir: str | None = None,
        aspect_ratio: str = "9:16",
    ) -> str:
        calls.append("imagen")
        return "storage/cache/paid.png"

    monkeypatch.setattr(image_router, "search_serper", fake_serper)
    monkeypatch.setattr(image_router, "generate_gemini_flash", fake_flash)
    monkeypatch.setattr(image_router, "generate_imagen", fake_imagen)

    _url, source = image_router.route_image({"image_prompt": "specific product photo"})

    assert source == "gemini-flash"
    assert calls == ["gemini-flash"]


def test_explicit_imagen_source_falls_back_to_free_stock_when_paid_disabled(monkeypatch):
    _disable_paid(monkeypatch)
    calls: list[str] = []

    def fake_flash(prompt: str, output_dir: str | None = None) -> None:
        calls.append("gemini-flash")
        return None

    def fake_imagen(
        prompt: str,
        output_dir: str | None = None,
        aspect_ratio: str = "9:16",
    ) -> str:
        calls.append("imagen")
        return "storage/cache/paid.png"

    def fake_pexels(query: str, orientation: str = "portrait") -> str:
        calls.append("pexels")
        return "https://pexels.example/free.jpg"

    monkeypatch.setattr(image_router, "generate_gemini_flash", fake_flash)
    monkeypatch.setattr(image_router, "generate_imagen", fake_imagen)
    monkeypatch.setattr(image_router, "search_pexels", fake_pexels)

    url, source = image_router.route_image({
        "image_prompt": "cinematic studio shot",
        "image_source": "imagen",
    })

    assert url == "https://pexels.example/free.jpg"
    assert source == "pexels"
    assert calls == ["gemini-flash", "pexels"]


def test_explicit_imagen_source_can_use_paid_after_opt_in(monkeypatch):
    _disable_paid(monkeypatch)
    monkeypatch.setenv("VIDEO_STUDIO_ALLOW_PAID_PROVIDERS", "true")
    calls: list[str] = []

    def fake_flash(prompt: str, output_dir: str | None = None) -> None:
        calls.append("gemini-flash")
        return None

    def fake_imagen(
        prompt: str,
        output_dir: str | None = None,
        aspect_ratio: str = "9:16",
    ) -> str:
        calls.append("imagen")
        return "storage/cache/paid.png"

    monkeypatch.setattr(image_router, "generate_gemini_flash", fake_flash)
    monkeypatch.setattr(image_router, "generate_imagen", fake_imagen)

    url, source = image_router.route_image({
        "image_prompt": "cinematic studio shot",
        "image_source": "imagen",
    })

    assert url.endswith("paid.png")
    assert source == "imagen"
    assert calls == ["gemini-flash", "imagen"]


def test_generate_imagen_writes_api_response_image(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    png_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1QAAAAASUVORK5CYII="

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, _limit: int) -> bytes:
            return json.dumps({
                "predictions": [{"bytesBase64Encoded": png_base64}],
            }).encode("utf-8")

    def fake_urlopen(_request, timeout: int):
        assert timeout == 60
        return FakeResponse()

    monkeypatch.setattr(image_router.urllib_request, "urlopen", fake_urlopen)

    image_path = image_router.generate_imagen("test prompt", output_dir=str(tmp_path))

    assert image_path is not None
    assert Path(image_path).exists()
    assert Path(image_path).read_bytes().startswith(b"\x89PNG")
