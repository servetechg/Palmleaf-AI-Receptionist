"""Forward-only SQL migrations (data-model.md §17).

    python -m grace_db.migrate            # apply everything pending
    python -m grace_db.migrate --status   # show applied/pending, change nothing

Deliberately not Alembic. The frozen data model specifies forward-only SQL with no ORM,
and every migration in `platform/postgres/migrations/` is hand-written DDL copied from
that document. A migration framework would add a dependency, an abstraction, and an
autogenerate feature we must never use — for a numbered-file runner that fits on a page.

Each file runs inside its own transaction. A failure leaves earlier files applied and the
failing one rolled back, which is the behaviour you want when a DDL statement is rejected
halfway down a file.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).resolve().parents[2] / "platform" / "postgres" / "migrations"

#: Records what has run. Created before anything else, by this module rather than by a
#: migration, because a migration cannot record itself before the table exists.
BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     text PRIMARY KEY,
  applied_at  timestamptz NOT NULL DEFAULT now()
)
"""


def database_url() -> str:
    url = os.environ.get("GRACE_DATABASE_URL")
    if not url:
        sys.exit(
            "✗ GRACE_DATABASE_URL is not set.\n"
            "  Local default (see .env.example):\n"
            "    postgresql://grace:grace-dev@localhost:5432/grace\n"
            "  Start the database first with:  make db-up"
        )
    return url


def discover() -> list[Path]:
    if not MIGRATIONS.is_dir():
        sys.exit(f"✗ no migrations directory at {MIGRATIONS}")
    return sorted(MIGRATIONS.glob("*.sql"))


def applied(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def main() -> int:
    parser = argparse.ArgumentParser(prog="grace-db-migrate")
    parser.add_argument("--status", action="store_true", help="report only, change nothing")
    args = parser.parse_args()

    files = discover()
    with psycopg.connect(database_url()) as conn:
        conn.execute(BOOTSTRAP)
        conn.commit()
        done = applied(conn)

        pending = [f for f in files if f.stem not in done]

        if args.status:
            print(f"\nMigrations in {MIGRATIONS}\n")
            for f in files:
                print(f"  {'✓' if f.stem in done else '·'} {f.stem}")
            print(f"\n{len(done)} applied, {len(pending)} pending\n")
            return 0

        if not pending:
            print(f"\n✓ database is up to date — {len(done)} migration(s) applied\n")
            return 0

        print(f"\nApplying {len(pending)} migration(s)\n")
        for f in pending:
            sql = f.read_text(encoding="utf-8")
            try:
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (f.stem,),
                    )
            except psycopg.Error as exc:
                print(f"  ✗ {f.stem}\n\n{exc}\n", file=sys.stderr)
                return 1
            print(f"  ✓ {f.stem}")

        print(f"\n✓ applied {len(pending)} migration(s)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
