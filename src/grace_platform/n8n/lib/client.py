"""Minimal n8n public-API client. Header is ``X-N8N-API-KEY``, not a bearer."""

from __future__ import annotations

from typing import Any

import httpx


class N8nError(RuntimeError):
    def __init__(self, status: int, method: str, path: str, body: str) -> None:
        super().__init__(f"{method} {path} → {status}\n{body}")
        self.status = status


class N8nClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        if not base_url:
            raise ValueError("N8N_API_URL is not set")
        if not api_key:
            raise ValueError("N8N_API_KEY is not set")
        self._client = httpx.Client(
            base_url=f"{base_url.rstrip('/')}/api/v1",
            headers={"X-N8N-API-KEY": api_key},
            timeout=30.0,
        )

    def __enter__(self) -> N8nClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self._client.close()

    def _req(self, method: str, path: str, body: Any = None) -> Any:
        res = self._client.request(method, path, json=body)
        if res.status_code >= 400:
            raise N8nError(res.status_code, method, path, res.text)
        return res.json() if res.content else {}

    def list_workflows(self, tags: list[str] | None = None) -> list[dict[str, Any]]:
        # Do not also pass projectId — n8n#19283, the two filters do not work together.
        q = "limit=250&excludePinnedData=true"
        if tags:
            q += "&tags=" + ",".join(tags)
        return list(self._req("GET", f"/workflows?{q}").get("data", []))

    def create_workflow(self, body: Any) -> dict[str, Any]:
        return dict(self._req("POST", "/workflows", body))

    def update_workflow(self, wf_id: str, body: Any) -> dict[str, Any]:
        """Body must be EXACTLY {name, nodes, connections, settings} — additionalProperties:false."""
        return dict(self._req("PUT", f"/workflows/{wf_id}", body))

    def set_tags(self, wf_id: str, tag_ids: list[str]) -> Any:
        return self._req("PUT", f"/workflows/{wf_id}/tags", [{"id": t} for t in tag_ids])

    def activate(self, wf_id: str) -> str:
        """Which route exists depends on the n8n version (04-n8n-layer §6.4).

        404 = route absent; 405 = path exists but POST is not allowed on this version.
        Observed 405 on palmleafmassage.app.n8n.cloud — catching only 404 was not enough.
        """
        try:
            self._req("POST", f"/workflows/{wf_id}/publish")
            return "publish"
        except N8nError as err:
            if err.status in (404, 405):
                self._req("POST", f"/workflows/{wf_id}/activate")
                return "activate"
            raise

    def list_credentials(self) -> list[dict[str, Any]]:
        # Secrets are never returned by this endpoint — only id, name, type, timestamps.
        return list(self._req("GET", "/credentials?limit=250").get("data", []))

    def list_tags(self) -> list[dict[str, Any]]:
        return list(self._req("GET", "/tags?limit=250").get("data", []))

    def create_tag(self, name: str) -> dict[str, Any]:
        return dict(self._req("POST", "/tags", {"name": name}))
