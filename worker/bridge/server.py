from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import load_dotenv

# Load .env before any adapter/tool probe reads os.environ
load_dotenv(Path.cwd() / ".env", override=False)

from worker.media.adapters import probe_local_media_adapters
from worker.media.model_router import ProviderAvailability, route_project_plan, summarize_cost
from worker.planner.ollama_planner import build_project_plan, probe_planner_runtime
from worker.planner.save_plan import save_project_bundle
from worker.render.compose import compose_smoke_render
from worker.runtime.tools import probe_tools

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 5161
PROJECT_ROOT = Path.cwd()
PYTHON_PATH = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _provider_availability(payload: dict) -> ProviderAvailability:
    availability = payload.get("availability", {})
    premium_enabled = bool(availability.get("premiumEnabled", False))
    return ProviderAvailability(
        sora2=bool(availability.get("sora2", False)),
        veo3=bool(availability.get("veo3", False)),
        premium_enabled=premium_enabled,
    )


def _planner_mode(payload: dict) -> str:
    planner_mode = str(payload.get("plannerMode", "auto")).strip().lower()
    if planner_mode in {"auto", "ollama", "sample"}:
        return planner_mode
    return "auto"


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "VideoStudioPythonBridge/0.1"
    _MAX_BODY_SIZE = 64 * 1024 * 1024  # 64 MB

    def _send_json(self, status_code: int, payload: dict) -> None:
        encoded = _json_bytes(payload)
        self.send_response(status_code)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5160")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > self._MAX_BODY_SIZE:
            raise ValueError(f"request body too large ({length} bytes, max {self._MAX_BODY_SIZE})")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5160")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/api/health":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        python_ready = PYTHON_PATH.exists()
        tools = probe_tools(PROJECT_ROOT)
        payload = {
            "ok": python_ready,
            "service": "video-studio-local-bridge",
            "port": BRIDGE_PORT,
            "projectRoot": str(PROJECT_ROOT),
            "pythonPath": str(PYTHON_PATH),
            "tools": {name: tool.to_dict() for name, tool in tools.items()},
            "planner": probe_planner_runtime().to_dict(),
            "media": {
                name: adapter.to_dict()
                for name, adapter in probe_local_media_adapters(PROJECT_ROOT).items()
            },
        }
        self._send_json(HTTPStatus.OK if python_ready else HTTPStatus.INTERNAL_SERVER_ERROR, payload)

    def do_POST(self) -> None:  # noqa: N802
        try:
            body = self._read_json()
            if self.path == "/api/route-plan":
                self._handle_route_plan(body)
                return

            if self.path == "/api/save-project":
                self._handle_save_project(body)
                return

            if self.path == "/api/render-smoke":
                self._handle_render_smoke(body)
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except Exception as error:  # pragma: no cover - exercised via smoke script
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        import sys
        sys.stderr.write(f"[bridge] {self.address_string()} {format % args}\n")

    def _handle_route_plan(self, body: dict) -> None:
        prompt = str(body.get("prompt", "")).strip()
        budget_mode = body.get("budgetMode")
        if not prompt:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "prompt is required"})
            return

        if budget_mode not in {"free", "standard", "premium"}:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "budgetMode must be free, standard, or premium"},
            )
            return

        availability = _provider_availability(body)
        plan, planner = build_project_plan(
            prompt,
            budget_mode=budget_mode,
            planner_mode=_planner_mode(body),
        )
        decisions = route_project_plan(plan, availability)
        self._send_json(
            HTTPStatus.OK,
            {
                "plan": plan.to_dict(),
                "planner": planner.to_dict(),
                "routes": [decision.to_dict() for decision in decisions],
                "estimatedTotalCostUsd": summarize_cost(decisions),
            },
        )

    def _handle_save_project(self, body: dict) -> None:
        prompt = str(body.get("prompt", "")).strip()
        budget_mode = body.get("budgetMode")
        project_id = str(body.get("projectId", "")).strip()
        if not prompt:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "prompt is required"})
            return

        if budget_mode not in {"free", "standard", "premium"}:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "budgetMode must be free, standard, or premium"},
            )
            return

        if not project_id:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "projectId is required"})
            return

        payload = save_project_bundle(
            prompt=prompt,
            budget_mode=budget_mode,
            availability=_provider_availability(body),
            planner_mode=_planner_mode(body),
            project_id=project_id,
            project_root=PROJECT_ROOT,
            scene_assets=body.get("sceneAssets"),
            provider_overrides=body.get("providerOverrides"),
        )
        self._send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "saveResult": payload["saveResult"],
                "planner": payload["planner"],
                "plan": payload["plan"],
                "routes": payload["routes"],
                "manifest": payload["manifest"],
            },
        )

    def _handle_render_smoke(self, body: dict) -> None:
        prompt = str(body.get("prompt", "")).strip()
        budget_mode = body.get("budgetMode")
        project_id = str(body.get("projectId", "")).strip()
        use_sse = body.get("stream", False)

        if not prompt:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "prompt is required"})
            return

        if budget_mode not in {"free", "standard", "premium"}:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "budgetMode must be free, standard, or premium"},
            )
            return

        if not project_id:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "projectId is required"})
            return

        payload = save_project_bundle(
            prompt=prompt,
            budget_mode=budget_mode,
            availability=_provider_availability(body),
            planner_mode=_planner_mode(body),
            project_id=project_id,
            project_root=PROJECT_ROOT,
            scene_assets=body.get("sceneAssets"),
            provider_overrides=body.get("providerOverrides"),
        )

        if use_sse:
            self._handle_render_sse(payload)
        else:
            render_result = compose_smoke_render(
                manifest_path=Path(payload["saveResult"]["manifestPath"]),
                project_root=PROJECT_ROOT,
            )
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "saveResult": payload["saveResult"],
                    "planner": payload["planner"],
                    "plan": payload["plan"],
                    "routes": payload["routes"],
                    "manifest": payload["manifest"],
                    "renderResult": render_result.to_dict(),
                },
            )

    def _handle_render_sse(self, payload: dict) -> None:
        """Stream render progress as SSE events."""
        self.send_response(HTTPStatus.OK)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5160")
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def _send_event(event: str, data: dict) -> None:
            line = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            self.wfile.write(line.encode("utf-8"))
            self.wfile.flush()

        manifest_path = Path(payload["saveResult"]["manifestPath"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        total_scenes = len(manifest.get("scenes", []))

        _send_event("progress", {"phase": "save", "message": "프로젝트 저장 완료", "current": 0, "total": total_scenes})

        try:
            render_result = compose_smoke_render(
                manifest_path=manifest_path,
                project_root=PROJECT_ROOT,
                progress_callback=lambda idx, scene_id: _send_event(
                    "progress",
                    {"phase": "scene", "message": f"장면 {idx + 1}/{total_scenes} 렌더 중", "current": idx + 1, "total": total_scenes, "sceneId": scene_id},
                ),
            )
            _send_event("done", {
                "ok": True,
                "saveResult": payload["saveResult"],
                "planner": payload["planner"],
                "plan": payload["plan"],
                "routes": payload["routes"],
                "manifest": payload["manifest"],
                "renderResult": render_result.to_dict(),
            })
        except Exception as error:
            _send_event("error", {"error": str(error)})


def serve() -> None:
    server = ThreadingHTTPServer((BRIDGE_HOST, BRIDGE_PORT), BridgeHandler)
    print(
        json.dumps(
            {
                "ok": True,
                "service": "video-studio-local-bridge",
                "port": BRIDGE_PORT,
                "projectRoot": str(PROJECT_ROOT),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> int:
    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
