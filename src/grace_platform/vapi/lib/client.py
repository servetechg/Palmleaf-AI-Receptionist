"""Minimal typed Vapi REST client. No SDK — the surface we need is small and stable."""

from __future__ import annotations

from typing import Any

import httpx

BASE = "https://api.vapi.ai"


class VapiError(RuntimeError):
    def __init__(self, status: int, method: str, path: str, body: str) -> None:
        super().__init__(f"{method} {path} → {status}\n{body}")
        self.status = status
        self.method = method
        self.path = path
        self.body = body


class VapiClient:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("VAPI_API_KEY is not set")
        self._client = httpx.Client(
            base_url=BASE,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    def __enter__(self) -> VapiClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self._client.close()

    def _req(self, method: str, path: str, body: Any = None) -> Any:
        res = self._client.request(method, path, json=body)
        if res.status_code >= 400:
            raise VapiError(res.status_code, method, path, res.text)
        return res.json() if res.content else {}

    # ── assistants ────────────────────────────────────────────────────────────
    def list_assistants(self) -> list[dict[str, Any]]:
        return list(self._req("GET", "/assistant?limit=100"))

    def get_assistant(self, assistant_id: str) -> dict[str, Any]:
        return dict(self._req("GET", f"/assistant/{assistant_id}"))

    def create_assistant(self, body: Any) -> dict[str, Any]:
        return dict(self._req("POST", "/assistant", body))

    def update_assistant(self, assistant_id: str, body: Any) -> dict[str, Any]:
        return dict(self._req("PATCH", f"/assistant/{assistant_id}", body))

    # ── tools ─────────────────────────────────────────────────────────────────
    def list_tools(self) -> list[dict[str, Any]]:
        return list(self._req("GET", "/tool?limit=200"))

    def create_tool(self, body: Any) -> dict[str, Any]:
        return dict(self._req("POST", "/tool", body))

    def update_tool(self, tool_id: str, body: Any) -> dict[str, Any]:
        return dict(self._req("PATCH", f"/tool/{tool_id}", body))

    # ── phone numbers ─────────────────────────────────────────────────────────
    def list_phone_numbers(self) -> list[dict[str, Any]]:
        return list(self._req("GET", "/phone-number?limit=100"))

    def create_phone_number(self, body: Any) -> dict[str, Any]:
        return dict(self._req("POST", "/phone-number", body))

    def update_phone_number(self, number_id: str, body: Any) -> dict[str, Any]:
        return dict(self._req("PATCH", f"/phone-number/{number_id}", body))

    # ── structured outputs ────────────────────────────────────────────────────
    def list_structured_outputs(self) -> list[dict[str, Any]]:
        raw = self._req("GET", "/structured-output?limit=100")
        if isinstance(raw, dict):
            results = raw.get("results", [])
            return list(results) if isinstance(results, list) else []
        return list(raw)

    def create_structured_output(self, body: Any) -> dict[str, Any]:
        return dict(self._req("POST", "/structured-output", body))

    def update_structured_output(self, so_id: str, body: Any) -> dict[str, Any]:
        return dict(self._req("PATCH", f"/structured-output/{so_id}", body))


def tool_identity(tool: dict[str, Any]) -> str:
    """Tool identity is ``function.name`` for function tools, else the tool ``type``."""
    fn = tool.get("function")
    if isinstance(fn, dict):
        name = fn.get("name")
        if isinstance(name, str) and name:
            return name
    tool_type = tool.get("type")
    return tool_type if isinstance(tool_type, str) else ""
