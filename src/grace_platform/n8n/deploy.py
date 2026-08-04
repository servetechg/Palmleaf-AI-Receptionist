"""n8n config-as-code deploy against a single Cloud instance (doc 09 §6.3, ADR-0013).

    python -m grace_platform.n8n.deploy --env dev --diff
    python -m grace_platform.n8n.deploy --env dev --apply

Dev and prod share the instance and are separated by tag + name prefix + webhook path
prefix + per-environment credentials. Anything not tagged ``managed:git`` is invisible to
this script — including workflows that were already on the instance.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .lib.client import N8nClient

DIR = Path(__file__).resolve().parents[3] / "platform" / "n8n" / "workflows"

CREDENTIAL_NAMES: dict[str, dict[str, str]] = {
    # Only one. n8n holds no third-party credentials — every notification goes through
    # Core API's /internal/notify/*, so 10DLC and opt-out enforcement cannot be bypassed
    # (doc 09 §3.4). Slack is not in scope; if adopted it becomes a Core API channel.
    "core-api": {"dev": "PalmLeaf Core API (dev)", "prod": "PalmLeaf Core API (prod)"},
}

WORKFLOW_ALIASES: dict[str, str] = {"wf-00": "WF-00", "wf-12": "WF-12", "wf-18": "WF-18"}

_WF_REF = re.compile(r"__WF__:([a-z0-9-]+)")
_WF_NUM = re.compile(r"(WF-\d+)")


def dependencies_of(wf: dict[str, Any]) -> list[str]:
    """Aliases this workflow references via ``__WF__:`` — what must be published first."""
    return sorted(set(_WF_REF.findall(json.dumps(wf))))


def render(
    file: str,
    wf: dict[str, Any],
    env: str,
    cred_ids: dict[str, str],
    workflow_ids: dict[str, str],
) -> dict[str, Any]:
    """Resolves placeholders and applies the environment prefix.

    An unresolved placeholder is a HARD FAILURE. n8n will not complain — it accepts the
    workflow, activates it, and then throws ``CredentialNotFoundError`` on the first
    execution, which is the worst possible time to find out (doc 09 §6.2).
    """
    unresolved: list[str] = []

    def resolve_credential(entry: dict[str, Any]) -> dict[str, Any]:
        """n8n stores ``{id: <real id>, name: <display name>}``.

        Both fields must be resolved *differently*: the id to the real credential id, the
        name to the human-readable name. Replacing both with the id looks fine on PUT, but
        n8n rewrites ``name`` back to the true value on save — so every subsequent diff
        reports a change that will never go away.
        """
        raw = str(entry.get("id", ""))
        if not raw.startswith("__CRED__:"):
            return entry
        alias = raw[len("__CRED__:") :]
        name = CREDENTIAL_NAMES.get(alias, {}).get(env)
        cred_id = cred_ids.get(name) if name else None
        if not cred_id:
            unresolved.append(f'credential "{alias}" → {name or "(no mapping)"}')
            return entry
        return {"id": cred_id, "name": name}

    def walk(v: Any, key: str = "") -> Any:
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            if key == "credentials":
                return {k: resolve_credential(x) for k, x in v.items()}
            return {k: walk(x, k) for k, x in v.items()}
        if not isinstance(v, str):
            return v
        if v.startswith("__CRED__:"):
            # Reached only if a placeholder appears outside a credentials object.
            unresolved.append(f'stray credential placeholder "{v}"')
            return v
        if v.startswith("__WF__:"):
            alias = v[len("__WF__:") :]
            prefix = WORKFLOW_ALIASES.get(alias)
            wf_id = workflow_ids.get(prefix) if prefix else None
            if not wf_id:
                unresolved.append(f'workflow "{alias}" → {prefix or "(no mapping)"}')
                return v
            return wf_id
        # Webhook paths carry the environment so dev and prod cannot collide.
        return v.replace("{{ENV}}/", f"{env}/")

    nodes = walk(wf["nodes"])
    settings = walk(wf.get("settings", {}))

    if unresolved:
        print(f"\n✗ {file}: unresolved placeholder(s):", file=sys.stderr)
        for u in unresolved:
            print(f"    {u}", file=sys.stderr)
        print(
            "\n  n8n would accept this workflow and then throw on its first execution.\n"
            "  Create the credential in the n8n UI (see credentials.example.json) and retry.\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # PUT body must be EXACTLY these four keys — the schema is additionalProperties:false.
    return {
        "name": f"[{env}] {wf['name']}",
        "nodes": nodes,
        "connections": wf["connections"],
        "settings": settings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="n8n-deploy")
    parser.add_argument("--env", choices=("dev", "prod"), default="dev")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--diff", action="store_true")
    args = parser.parse_args()
    env, apply = args.env, args.apply

    print(f"\nn8n deploy — env={env} mode={'APPLY' if apply else 'DIFF'}\n")
    managed_tags = ["managed:git", f"env:{env}"]
    changes = 0

    with N8nClient(os.environ.get("N8N_API_URL", ""), os.environ.get("N8N_API_KEY", "")) as client:
        tag_ids = {t["name"]: t["id"] for t in client.list_tags()}
        for name in managed_tags:
            if name in tag_ids:
                continue
            if apply:
                tag_ids[name] = client.create_tag(name)["id"]
                print(f"  + tag {name}")
            else:
                print(f"  + tag {name} (would create)")

        cred_ids = {c["name"]: c["id"] for c in client.list_credentials()}
        managed = client.list_workflows(managed_tags)
        by_name = {w["name"]: w for w in managed}
        workflow_ids: dict[str, str] = {}
        for w in managed:
            m = re.match(r"^\[(?:dev|prod)\]\s+(WF-\d+)", str(w["name"]))
            if m:
                workflow_ids[m.group(1)] = str(w["id"])

        local = [(p.name, json.loads(p.read_text("utf-8"))) for p in sorted(DIR.glob("*.json"))]
        resolved_tag_ids = [tag_ids[t] for t in managed_tags if t in tag_ids]

        # n8n refuses to publish a workflow whose sub-workflows are not yet published, so
        # activation has to happen in dependency order.
        pending: list[tuple[str, str, list[str]]] = []

        # Create everything first so __WF__ cross-references can resolve.
        if apply:
            for _file, wf in local:
                target = f"[{env}] {wf['name']}"
                if target in by_name:
                    continue
                created = client.create_workflow(
                    {"name": target, "nodes": [], "connections": {}, "settings": {}}
                )
                # Tag IMMEDIATELY. If a later step fails, the partially-created workflow is
                # still inside the managed set — so the next run finishes it instead of
                # creating a second copy and leaving an untagged orphan behind.
                client.set_tags(str(created["id"]), resolved_tag_ids)
                by_name[target] = created
                m = _WF_NUM.match(str(wf["name"]))
                if m:
                    workflow_ids[m.group(1)] = str(created["id"])
                print(f"  + workflow {target} → {created['id']}")
                changes += 1

        for file, wf in local:
            target = f"[{env}] {wf['name']}"
            remote = by_name.get(target)
            body = render(file, wf, env, cred_ids, workflow_ids)

            if remote is None:
                print(f"  + workflow {target} (would create)")
                changes += 1
                continue

            same = json.dumps(remote.get("nodes", [])) == json.dumps(body["nodes"]) and json.dumps(
                remote.get("connections", {})
            ) == json.dumps(body["connections"])
            if same:
                print(f"  = workflow {target}")
                continue

            changes += 1
            print(f"  ~ workflow {target}")
            if not apply:
                continue
            client.update_workflow(str(remote["id"]), body)
            client.set_tags(str(remote["id"]), resolved_tag_ids)
            pending.append((str(remote["id"]), target, dependencies_of(wf)))
            print("      updated and tagged")

        # Activate in dependency order: a referenced sub-workflow must be published first.
        if apply and pending:
            done: set[str] = set()
            queue = list(pending)
            # Bound on the ORIGINAL length: `queue` shrinks each pass, so comparing against
            # it exits one pass early and silently leaves the last workflow unactivated.
            for _ in range(len(queue) + 1):
                if not queue:
                    break

                def alias_of(label: str) -> str:
                    m = _WF_NUM.search(label)
                    return m.group(1).lower() if m else ""

                ready = [w for w in queue if all(d in done or d == alias_of(w[1]) for d in w[2])]
                batch = ready or queue  # nothing ready: surface n8n's error rather than stall
                for wf_id, label, _deps in batch:
                    route = client.activate(wf_id)
                    print(f"  ▶ activated {label} via /{route}")
                    done.add(alias_of(label))
                queue = [w for w in queue if w not in batch]

        local_names = {f"[{env}] {wf['name']}" for _f, wf in local}
        for w in managed:
            if w["name"] not in local_names:
                print(
                    f'\n✗ orphan: "{w["name"]}" is tagged managed:git,env:{env} but has no local file',
                    file=sys.stderr,
                )
                return 1

    print()
    if apply:
        print(f"✓ applied — {changes} change(s)\n")
        return 0
    if changes == 0:
        print("✓ no drift\n")
        return 0
    print(f"⚠ {changes} pending change(s). Re-run with --apply.\n")
    return 1 if os.environ.get("CI") else 0


if __name__ == "__main__":
    raise SystemExit(main())
