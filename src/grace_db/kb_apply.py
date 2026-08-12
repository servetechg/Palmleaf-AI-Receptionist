"""Apply the knowledge base from YAML into `knowledge_entries`.

    make kb-apply

The editing surface for a non-developer is one commented YAML file; this turns it into
rows. Deliberately one-directional — the file is the source of truth, and the table is a
projection of it. Editing the table by hand is not supported, because then the file lies.

**Vagaro never writes this table.** It holds the words the client signed off, not synced
data. Prices live in `services` (which Vagaro will sync); knowledge answers hold what is
*said*, and reference nothing that could drift out of step.

`approved: false` clears `approved_at`, which makes Grace treat the entry as absent and
offer a person instead. That is the safety: an answer nobody signed off never reaches a
caller.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import psycopg
import yaml

from .migrate import database_url

APPROVED_BY = "palmleaf questionnaire 2026-07-28"
TENANT_SLUG = "palmleaf"


def load(path: Path) -> list[dict[str, Any]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        sys.exit(f"✗ {path}: expected a list of entries, got {type(raw).__name__}")

    entries: list[dict[str, Any]] = []
    for i, entry in enumerate(raw, start=1):
        missing = {"key", "category", "answer"} - set(entry)
        if missing:
            sys.exit(f"✗ {path}: entry {i} is missing {', '.join(sorted(missing))}")
        answer = " ".join(str(entry["answer"]).split())  # collapse YAML folding
        if not answer:
            sys.exit(f"✗ {path}: entry '{entry['key']}' has an empty answer")
        entries.append(
            {
                "key": str(entry["key"]),
                "category": str(entry["category"]),
                "answer": answer,
                "approved": bool(entry.get("approved", False)),
                "aliases": list(entry.get("aliases", [])),
            }
        )
    return entries


def apply(conn: psycopg.Connection, entries: list[dict[str, Any]]) -> tuple[int, int, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM tenants WHERE slug = %s", (TENANT_SLUG,))
        row = cur.fetchone()
        if row is None:
            sys.exit(f"✗ no tenant '{TENANT_SLUG}' — run `make db-seed` first")
        tenant_id = row[0]

        approved = 0
        for entry in entries:
            cur.execute(
                """
                INSERT INTO knowledge_entries
                  (tenant_id, key, category, question_aliases, answer_spoken,
                   active, approved_at, approved_by)
                VALUES (%s, %s, %s, %s, %s, true,
                        CASE WHEN %s THEN now() ELSE NULL END,
                        CASE WHEN %s THEN %s ELSE NULL END)
                ON CONFLICT (tenant_id, key) DO UPDATE SET
                    category         = EXCLUDED.category,
                    question_aliases = EXCLUDED.question_aliases,
                    answer_spoken    = EXCLUDED.answer_spoken,
                    active           = true,
                    approved_at      = EXCLUDED.approved_at,
                    approved_by      = EXCLUDED.approved_by,
                    updated_at       = now()
                """,
                (
                    tenant_id,
                    entry["key"],
                    entry["category"],
                    entry["aliases"],
                    entry["answer"],
                    entry["approved"],
                    entry["approved"],
                    APPROVED_BY,
                ),
            )
            approved += int(entry["approved"])

        # A key removed from the file is deactivated, never deleted: a previously spoken
        # answer is worth keeping for "what did we tell callers last month?".
        cur.execute(
            """
            UPDATE knowledge_entries
            SET active = false, approved_at = NULL, updated_at = now()
            WHERE tenant_id = %s AND active AND key <> ALL(%s)
            """,
            (tenant_id, [e["key"] for e in entries]),
        )
        retired = cur.rowcount

    return len(entries), approved, retired


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit("usage: python -m grace_db.kb_apply <path/to/knowledge.yaml>")
    path = Path(sys.argv[1])
    if not path.is_file():
        sys.exit(f"✗ no such file: {path}")

    entries = load(path)
    try:
        with psycopg.connect(database_url()) as conn:
            total, approved, retired = apply(conn, entries)
            conn.commit()
    except psycopg.OperationalError as exc:
        print(f"✗ cannot reach the database: {exc}", file=sys.stderr)
        return 1

    print(f"\n✓ knowledge base applied — {total} entr{'y' if total == 1 else 'ies'}")
    print(f"    {approved} approved (Grace may speak these)")
    if total - approved:
        print(f"    {total - approved} awaiting sign-off — Grace offers a person instead")
    if retired:
        print(f"    {retired} retired (removed from the file)")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
