"""n8n config-as-code deploy against a single Cloud instance (04-n8n-layer §6.3, ADR-0013).

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
    "vapi": {"dev": "PalmLeaf Vapi (dev)", "prod": "PalmLeaf Vapi (prod)"},
    # Present so a disabled node's placeholder resolves if the credential ever appears;
    # the node stays off until someone enables it deliberately.
    "postgres": {"dev": "PalmLeaf Postgres (dev)", "prod": "PalmLeaf Postgres (prod)"},
    # n8n holds no notification credentials — every staff notification goes through
    # Core API's /internal/notify/*, so 10DLC and opt-out enforcement live in one place
    # and cannot be bypassed by adding a node to a canvas (04-n8n-layer.md §3.4).
    "core-api": {"dev": "PalmLeaf Core API (dev)", "prod": "PalmLeaf Core API (prod)"},
    # Inbound auth for worker → n8n. n8n's Webhook node verifies a Header Auth credential
    # natively, which works on Cloud — unlike verifying an HMAC inside a Code node, which
    # cannot read the secret at all (Q-04.5, resolved 2026-08-05). WF-12 and WF-17 both use this.
    "n8n-inbound": {"dev": "PalmLeaf n8n Inbound (dev)", "prod": "PalmLeaf n8n Inbound (prod)"},
    # Outbound email for the nightly report. Deferred with Vagaro/RingCentral access.
    "smtp": {"dev": "PalmLeaf Email (dev)", "prod": "PalmLeaf Email (prod)"},
}

_WF_ALIAS = re.compile(r"^wf-(\d+)$")


def _alias_prefix(alias: str) -> str | None:
    """ "wf-23" -> "WF-23". Validated, not looked up — every real alias has this exact shape."""
    m = _WF_ALIAS.match(alias)
    return f"WF-{m.group(1)}" if m else None


#: Base URLs a workflow needs, resolved from the environment AT DEPLOY TIME.
#:
#: They cannot be read at runtime with ``$env``: n8n Cloud blocks environment access inside
#: nodes (``N8N_BLOCK_ENV_ACCESS_IN_NODE`` defaults on), so an expression like
#: ``{{ $env.GRACE_CORE_API_URL }}`` fails with "access to env vars denied" on every execution.
#: Verified against the live instance on 2026-08-04, where it was silently breaking WF-00 —
#: the global error handler — so no workflow failure was being reported at all.
URL_VARS: dict[str, str] = {
    "core-api": "GRACE_CORE_API_URL",
    # Secondary fan-out consumers (WF-17). Endpoints unknown until the client names them;
    # both nodes ship disabled, so an unset value cannot reach anything.
    "crm": "GRACE_CRM_WEBHOOK_URL",
    "marketing": "GRACE_MARKETING_WEBHOOK_URL",
}

#: Obvious, non-routable placeholder. Core API does not exist yet, so a deploy must not be
#: blocked by its URL being unset — but the value must never look like it might work.
URL_UNSET = "https://core-api.not-built.invalid"

#: Report recipients, resolved from the environment AT DEPLOY TIME — same reason as URL_VARS
#: (n8n Cloud blocks $env inside nodes). Deliberately NOT given a safe-fallback constant like
#: URL_UNSET: an unreachable URL 404s harmlessly, but a wrong email address either bounces
#: somewhere unintended or silently reaches nobody. An unset recipient blocks the deploy of
#: whichever workflow needs it, exactly like an unresolved credential — that is the correct
#: failure mode for a real-world side effect with no safe placeholder value.
EMAIL_VARS: dict[str, str] = {
    "reports-to": "GRACE_REPORTS_EMAIL_TO",
}

_WF_REF = re.compile(r"__WF__:([a-z0-9-]+)")
_WF_NUM = re.compile(r"(WF-\d+)")


def dependencies_of(wf: dict[str, Any]) -> list[str]:
    """Aliases this workflow references via ``__WF__:`` — what must be published first."""
    return sorted(set(_WF_REF.findall(json.dumps(wf))))


def in_dependency_order(
    local: list[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    """Sub-workflows before their callers.

    n8n rejects the **PUT itself** — not merely the activation — when a node references an
    unpublished sub-workflow: *"Cannot publish workflow: Node X references workflow Y which is
    not published."* So a caller has to be written and published after everything it calls,
    which alphabetical file order does not give (WF-07 calls WF-23).
    """
    by_alias: dict[str, tuple[str, dict[str, Any]]] = {}
    for entry in local:
        m = _WF_NUM.match(str(entry[1]["name"]))
        if m:
            by_alias[m.group(1).lower()] = entry

    ordered: list[tuple[str, dict[str, Any]]] = []
    placed: set[str] = set()

    def visit(entry: tuple[str, dict[str, Any]], stack: set[str]) -> None:
        name = entry[0]
        if name in placed or name in stack:
            return  # already placed, or a cycle — emit in the order found rather than looping
        stack.add(name)
        for dep in dependencies_of(entry[1]):
            target = by_alias.get(dep)
            if target is not None and target[0] != name:
                visit(target, stack)
        stack.discard(name)
        placed.add(name)
        ordered.append(entry)

    for entry in local:
        visit(entry, set())
    return ordered


def render(
    file: str,
    wf: dict[str, Any],
    env: str,
    cred_ids: dict[str, str],
    workflow_ids: dict[str, str],
) -> dict[str, Any] | None:
    """Resolves placeholders and applies the environment prefix.

    Returns ``None`` when the workflow is blocked on configuration the operator has not
    supplied yet — the caller skips it and continues with the rest.

    An unresolved placeholder is a HARD FAILURE. n8n will not complain — it accepts the
    workflow, activates it, and then throws ``CredentialNotFoundError`` on the first
    execution, which is the worst possible time to find out (04-n8n-layer §6.2).
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
        if "__URL__:" in v:
            # Usually "__URL__:core-api/internal/notify/ops" — resolve the alias, keep the path.
            for url_alias, url_var in URL_VARS.items():
                token = f"__URL__:{url_alias}"
                if token in v:
                    return v.replace(token, os.environ.get(url_var) or URL_UNSET)
            unresolved.append(f'url placeholder "{v}" has no mapping')
            return v
        if "__EMAIL__:" in v:
            for email_alias, email_var in EMAIL_VARS.items():
                token = f"__EMAIL__:{email_alias}"
                if token in v:
                    val = os.environ.get(email_var)
                    if not val:
                        unresolved.append(f'email "{v}" — set {email_var}')
                        return v
                    return v.replace(token, val)
            unresolved.append(f'email placeholder "{v}" has no mapping')
            return v
        if v.startswith("__WF__:"):
            alias = v[len("__WF__:") :]
            prefix = _alias_prefix(alias)
            wf_id = workflow_ids.get(prefix) if prefix else None
            if not wf_id:
                unresolved.append(f'workflow "{alias}" → {prefix or "(no mapping)"}')
                return v
            return wf_id
        # Webhook paths carry the environment so dev and prod cannot collide.
        return v.replace("{{ENV}}/", f"{env}/")

    # Disabled nodes are the Postgres path, shipped present-but-off. Their credential does
    # not exist yet — and n8n REJECTS a node referencing a credential id it cannot resolve
    # even when the node is disabled ("You don't have access to the credentials in the ..."
    # node), so the placeholder cannot simply be left in place. Strip the credentials block;
    # everything else about the node survives, and attaching a real credential when the node
    # is enabled is a one-field change in the n8n UI.
    def strip_unresolved_creds(node: dict[str, Any]) -> dict[str, Any]:
        out = dict(node)
        creds = {
            k: v
            for k, v in (out.get("credentials") or {}).items()
            if not str(v.get("id", "")).startswith("__CRED__:")
            or CREDENTIAL_NAMES.get(str(v["id"])[len("__CRED__:") :], {}).get(env) in cred_ids
        }
        if creds:
            out["credentials"] = creds
        else:
            out.pop("credentials", None)
        return out

    enabled = [n for n in wf["nodes"] if not n.get("disabled")]
    disabled = [strip_unresolved_creds(n) for n in wf["nodes"] if n.get("disabled")]
    nodes = walk(enabled) + [walk(n) for n in disabled]
    settings = walk(wf.get("settings", {}))

    if unresolved:
        # Blocked on configuration, not broken. Returning None makes the caller SKIP this
        # workflow — never create it, never activate it — while the rest of the set deploys.
        #
        # Aborting the whole run instead (the previous behaviour) meant one credential the
        # operator had not created yet held back every other workflow, which is the wrong
        # trade in a phase where several integrations are deliberately waiting on access.
        # The guarantee that matters is preserved: a workflow that would throw on its first
        # execution is still never published.
        print(f"\n  ⚠ SKIPPED {file} — blocked on configuration:", file=sys.stderr)
        for u in unresolved:
            print(f"      {u}", file=sys.stderr)
        print(
            "      create it in the n8n UI (see credentials.example.json), then re-run\n",
            file=sys.stderr,
        )
        return None

    # PUT body must be EXACTLY these four keys — the schema is additionalProperties:false.
    return {
        "name": f"[{env}] {wf['name']}",
        "nodes": nodes,
        "connections": wf["connections"],
        "settings": settings,
    }


def comparable(remote_nodes: list[Any], local_nodes: list[Any]) -> list[Any]:
    """Remote nodes, with server-assigned fields we never declared removed.

    n8n mints a ``webhookId`` on save for some node types even when the committed file has
    none. Comparing raw then reports a difference that **can never be resolved** — the same
    non-converging-diff failure the credential-name bug caused, and it is why WF-07 stayed
    permanently "changed" after its first deploy.

    A ``webhookId`` the local file *does* declare is preserved and compared: dropping those
    would change a live webhook URL, which is exactly what must not happen.
    """
    by_name = {n.get("name"): n for n in local_nodes if isinstance(n, dict)}
    out: list[Any] = []
    for node in remote_nodes:
        if not isinstance(node, dict):
            out.append(node)
            continue
        local = by_name.get(node.get("name"), {})
        cleaned = dict(node)
        if "webhookId" not in local:
            cleaned.pop("webhookId", None)
        out.append(cleaned)
    return out


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

        local = in_dependency_order(
            [(p.name, json.loads(p.read_text("utf-8"))) for p in sorted(DIR.glob("*.json"))]
        )
        blocked: list[str] = []
        resolved_tag_ids = [tag_ids[t] for t in managed_tags if t in tag_ids]

        # n8n refuses to publish a workflow whose sub-workflows are not yet published, so
        # activation has to happen in dependency order. `local` is already sorted that way;
        # `pending` now only carries the reconcile-the-inactive pass below.
        pending: list[tuple[str, str, list[str]]] = []
        done_now: set[str] = set()

        # Create everything first so __WF__ cross-references can resolve.
        if apply:
            for _file, wf in local:
                target = f"[{env}] {wf['name']}"
                if target in by_name:
                    continue
                if render(_file, wf, env, cred_ids, workflow_ids) is None:
                    continue  # blocked on configuration — do not create a half-built shell
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
            if body is None:
                blocked.append(target)
                continue

            if remote is None:
                print(f"  + workflow {target} (would create)")
                changes += 1
                continue

            same = json.dumps(comparable(remote.get("nodes", []), body["nodes"])) == json.dumps(
                body["nodes"]
            ) and json.dumps(remote.get("connections", {})) == json.dumps(body["connections"])
            if same:
                print(f"  = workflow {target}")
                # An unchanged workflow can still be INACTIVE (an earlier run aborting
                # part-way is enough). It must be published here, in dependency order — a
                # changed caller later in this loop would otherwise fail its PUT against an
                # unpublished target, and die before the reconcile pass below could fix it.
                if apply and not remote.get("active"):
                    route = client.activate(str(remote["id"]))
                    done_now.add(str(remote["id"]))
                    print(f"      ▶ was deployed but inactive — activated via /{route}")
                continue

            changes += 1
            print(f"  ~ workflow {target}")
            if not apply:
                continue
            client.update_workflow(str(remote["id"]), body)
            client.set_tags(str(remote["id"]), resolved_tag_ids)
            print("      updated and tagged")
            # Publish NOW, not in a later pass: the next workflow in this loop may reference
            # this one, and n8n refuses to write a caller whose target is still unpublished.
            route = client.activate(str(remote["id"]))
            done_now.add(str(remote["id"]))
            print(f"      ▶ activated via /{route}")

        # Reconcile activation, not just changes. A workflow whose definition already matches
        # is reported "=" and never queued above — so one that was created but not activated
        # (an earlier run aborting part-way is enough) would stay inactive forever, silently.
        # Deployed and running are different states; only the second one does any work.
        if apply:
            queued = {wf_id for wf_id, _label, _deps in pending} | done_now
            for _file, wf in local:
                target = f"[{env}] {wf['name']}"
                remote = by_name.get(target)
                if remote is None or target in blocked or str(remote["id"]) in queued:
                    continue
                if not remote.get("active"):
                    pending.append((str(remote["id"]), target, dependencies_of(wf)))
                    print(f"  ↑ {target} is deployed but inactive — activating")

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
        if blocked:
            print(f"\n  {len(blocked)} workflow(s) waiting on configuration, not deployed:")
            for b in blocked:
                print(f"    · {b}")
            print("  Everything else deployed. Create the credential, re-run, and they join in.")
        print(f"\n✓ applied — {changes} change(s)\n")
        return 0
    if changes == 0:
        print("✓ no drift\n")
        return 0
    print(f"⚠ {changes} pending change(s). Re-run with --apply.\n")
    return 1 if os.environ.get("CI") else 0


if __name__ == "__main__":
    raise SystemExit(main())
