"""Dev-only stand-in for Core API (doc 08 §10).

Exposes the SAME two routes with the SAME envelope as Core API will, so switching over
later is one environment variable. Its real job is not returning plausible strings — it is
**validating every tool call against the real Pydantic models from grace_contracts**, which
proves the JSON Schema published to Vapi and the schema our handlers expect actually agree,
under a live model, before Core API exists.

    python -m grace_platform.vapi.mock_server.server

Fault injection, for exercising the deadline fallbacks:
    GRACE_MOCK_LATENCY_MS=1200            add latency to every tool
    GRACE_MOCK_FAIL=checkAvailability     that tool returns a graceful failure sentence
    GRACE_MOCK_TIMEOUT=createBooking      that tool never responds
    GRACE_MOCK_NOW=2026-08-04T14:00:00Z   freeze the clock
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from pydantic import ValidationError

from grace_contracts import get_tool_spec, parse_tool_arguments

from .fixtures import FIXTURES

PORT = int(os.environ.get("GRACE_MOCK_PORT", "4242"))
LATENCY = int(os.environ.get("GRACE_MOCK_LATENCY_MS", "0"))
FAIL_TOOL = os.environ.get("GRACE_MOCK_FAIL", "")
TIMEOUT_TOOL = os.environ.get("GRACE_MOCK_TIMEOUT", "")

# Proves the `{call_id}:{tool_call_id}` key shape and the replay-stored-response path (I3).
_idempotency: dict[str, str] = {}
# Whisper text primed by flagEscalation, keyed by call id (doc 08 §7.1). 60s TTL.
_whispers: dict[str, tuple[str, float]] = {}


def log(kind: str, msg: str) -> None:
    print(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}  {kind:<9} {msg}", flush=True)


def _snake(name: str) -> str:
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in name)


def handle_tool_calls(payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("message", {})
    call = message.get("call") or payload.get("call") or {}
    call_id = call.get("id", "unknown-call")
    results: list[dict[str, Any]] = []

    for tc in message.get("toolCalls", []):
        fn = tc.get("function", {})
        name = fn.get("name", "")
        tool_call_id = tc.get("id", "unknown")
        spec = get_tool_spec(name)

        if spec is None:
            log("TOOL", f'✗ unknown tool "{name}"')
            results.append(
                {
                    "toolCallId": tool_call_id,
                    "name": name,
                    "result": "I'm not able to do that — let me get someone who can.",
                }
            )
            continue

        if name == TIMEOUT_TOOL:
            log("FAULT", f"{name} — simulating a hang (no response)")
            time.sleep(60)
            continue

        key = f"{call_id}:{tool_call_id}"
        if key in _idempotency:
            log("IDEMPOT", f"{name} replayed for {key}")
            results.append({"toolCallId": tool_call_id, "name": name, "result": _idempotency[key]})
            continue

        raw_args = parse_tool_arguments(fn.get("arguments", {}))
        # THE point of this server: validate with the real model, not a loose parse.
        # Vapi sends camelCase; the models are snake_case.
        try:
            spec.input_model.model_validate({_snake(k): v for k, v in raw_args.items()})
        except ValidationError as err:
            detail = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}"
                for e in err.errors()
            )
            log("SCHEMA", f"✗ {name} — {detail}")
            print(f"           args: {json.dumps(raw_args)}", flush=True)
            results.append(
                {
                    "toolCallId": tool_call_id,
                    "name": name,
                    "result": "Sorry, I didn't catch that properly — could you say it again?",
                }
            )
            continue

        if name == "flagEscalation" and raw_args.get("summary"):
            _whispers[call_id] = (str(raw_args["summary"]), time.time())

        if name == FAIL_TOOL:
            log("FAULT", f"{name} — simulating failure")
            results.append(
                {
                    "toolCallId": tool_call_id,
                    "name": name,
                    "result": "I'm having trouble with that right now. Let me get someone who can help.",
                }
            )
            continue

        if LATENCY:
            time.sleep(LATENCY / 1000)

        result = FIXTURES[name](raw_args, call_id)
        if spec.is_write:
            _idempotency[key] = result
        log("TOOL", f"✓ {name} → {result[:80]}")
        results.append({"toolCallId": tool_call_id, "name": name, "result": result})

    return {"results": results}


def handle_event(payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("message", {})
    mtype = message.get("type", "")
    call_id = (message.get("call") or {}).get("id", "unknown")

    if mtype == "transfer-destination-request":
        primed = _whispers.get(call_id)
        fresh = primed is not None and time.time() - primed[1] < 60
        if not fresh:
            # The prompt requires flagEscalation first. If it did not happen that is a
            # prompt-adherence failure worth seeing, not something to paper over.
            log("WHISPER", f"⚠ no primed whisper for {call_id} — model skipped flagEscalation")
        log("EVENT", f"transfer-destination-request (whisper: {'primed' if fresh else 'MISSING'})")
        return {
            "destination": {
                "type": "number",
                "number": os.environ.get("GRACE_FRONT_DESK_NUMBER", "+18475550123"),
                "callerId": "{{customer.number}}",
                "message": "One moment — connecting you to the front desk.",
                "transferPlan": {
                    "mode": "warm-transfer-experimental",
                    "message": primed[0]
                    if (fresh and primed)
                    else "Transferring a caller — no context captured.",
                    "sipVerb": "dial",
                    "dialTimeout": 25,
                    "fallbackPlan": {
                        "message": "I'm sorry — nobody's picking up right now. Let me take a message.",
                        "endCallEnabled": False,
                    },
                },
            }
        }

    if mtype == "end-of-call-report":
        analysis = message.get("analysis") or {}
        log("EVENT", f"end-of-call-report for {call_id}")
        structured = analysis.get("structuredData")
        log(
            "ANALYSIS",
            json.dumps(structured)
            if structured
            else "⚠ no structuredData — check artifactPlan.structuredOutputIds",
        )
        return {"ok": True}

    log("EVENT", f"{mtype} for {call_id}")
    return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:  # silence the default access log
        pass

    def _send(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {}
            if self.path.startswith("/vapi/tools"):
                self._send(200, handle_tool_calls(payload))
            elif self.path.startswith("/webhooks/vapi/events"):
                self._send(200, handle_event(payload))
            else:
                self._send(404, {"error": "not found"})
        except Exception as err:
            log("ERROR", str(err))
            self._send(
                200,
                {"results": [{"toolCallId": "unknown", "result": "Sorry — something went wrong."}]},
            )


def main() -> None:
    print(f"\n  Grace mock tool server  →  http://localhost:{PORT}")
    print("    POST /vapi/tools" + (f"   (+{LATENCY}ms latency)" if LATENCY else ""))
    print("    POST /webhooks/vapi/events")
    if FAIL_TOOL:
        print(f"    fault: {FAIL_TOOL} will fail")
    if TIMEOUT_TOOL:
        print(f"    fault: {TIMEOUT_TOOL} will hang")
    if os.environ.get("GRACE_MOCK_NOW"):
        print(f"    clock frozen at {os.environ['GRACE_MOCK_NOW']}")
    print()
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
