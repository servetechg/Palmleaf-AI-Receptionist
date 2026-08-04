"""Enforces the document template across Docs/plans/ and Docs/reference/.

The 20-document set diverged in five specific ways — a header block present in 7 of 20,
acceptance criteria under three different heading names, section numbering starting at 0 or 1
or absent, prompt content leaking into the heading tree, and four cross-reference syntaxes one
of which embeds line numbers that rot on any edit.

This makes the template mechanical so it cannot drift back.

    python -m grace_platform.docs.lint_docs
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "Docs"
TARGETS = (ROOT / "plans", ROOT / "reference")

# Docs/generated/ is machine-written and Docs/Completed/ is a historical record; neither
# follows the planning template.
SKIP_DIRS = {"generated", "Completed"}

REQUIRED_HEADER = ("**Status:**", "**Read before:**", "**Last verified:**")

#: Terms that must not appear at all — the stack we no longer use, and a platform we do not use.
BANNED = {
    "slack": "Slack is out of scope (removed 2026-08-03)",
    "typescript": "TypeScript was replaced by Python (ADR-0014)",
    "pnpm": "pnpm was replaced by uv (ADR-0014)",
    "fastify": "Fastify was replaced by FastAPI (ADR-0017)",
    "drizzle": "Drizzle was replaced by SQLAlchemy (ADR-0016)",
    "bullmq": "BullMQ was replaced by arq (ADR-0015)",
    "vitest": "Vitest was replaced by pytest (ADR-0014)",
    "eslint": "ESLint boundary rules were replaced by import-linter (ADR-0018)",
    "turborepo": "Turborepo was replaced by a Makefile (ADR-0014)",
}

#: A banned term is allowed on a line that explains the replacement.
EXEMPT_LINE = re.compile(
    r"supersed|replac|~~|was replaced|no longer|out of scope|historical|ADR-00(01|09)\b",
    re.I,
)

#: `§03 §116` — a line number dressed as a section. Rots silently on any edit.
LINE_NUMBER_XREF = re.compile(r"§\s*\d{2}\s+§\s*\d{3,}")

problems: list[str] = []


def fail(path: Path, line: int | None, msg: str) -> None:
    where = f"{path.relative_to(ROOT.parent)}" + (f":{line}" if line else "")
    problems.append(f"{where}  {msg}")


def strip_fences(text: str) -> list[tuple[int, str]]:
    """Returns (line_number, line) for lines OUTSIDE fenced code blocks."""
    out: list[tuple[int, str]] = []
    in_fence = False
    for i, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append((i, line))
    return out


def lint(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    outside = strip_fences(text)
    head = text.split("\n\n", 3)
    header_blob = "\n".join(head[:2])

    # 1. exactly one H1, and it is the first line
    h1s = [ln for _, ln in outside if ln.startswith("# ")]
    if len(h1s) != 1:
        fail(path, None, f"expected exactly one H1, found {len(h1s)}")
    elif not text.startswith("# "):
        fail(path, 1, "the H1 must be the first line")

    # 2. header block
    for field in REQUIRED_HEADER:
        if field not in header_blob:
            fail(path, None, f"header is missing {field}")

    # 3. no H2 inside a fence leaking into the outline.
    #    This is what makes the Vapi prompt content look like ten top-level sections.
    in_fence = False
    for i, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence and re.match(r"^#{1,3} ", line):
            fail(path, i, "heading inside a fenced block — breaks every table of contents")

    # 4. numbered sections, starting at 1, contiguous
    numbered = [(i, int(m.group(1))) for i, ln in outside if (m := re.match(r"^## (\d+)\.", ln))]
    if numbered:
        nums = [n for _, n in numbered]
        if nums[0] != 1:
            fail(path, numbered[0][0], f"sections must start at 1, found {nums[0]}")
        expected = list(range(1, len(nums) + 1))
        if nums != expected:
            fail(path, None, f"section numbers are not contiguous: {nums}")

    # 5. required trailing sections, by exact name
    h2s = [ln.strip() for _, ln in outside if ln.startswith("## ")]
    if not any(h.endswith("Acceptance criteria") for h in h2s):
        fail(path, None, 'missing a "## N. Acceptance criteria" section')
    if not any(h.endswith("Open questions") for h in h2s):
        fail(path, None, 'missing a "## N. Open questions" section (empty is fine, absent is not)')

    # 6. banned vocabulary
    for i, line in outside:
        low = line.lower()
        if EXEMPT_LINE.search(line):
            continue
        for term, why in BANNED.items():
            if re.search(rf"\b{re.escape(term)}\b", low):
                fail(path, i, f'"{term}" — {why}')

    # 7. cross-reference syntax
    for i, line in outside:
        if LINE_NUMBER_XREF.search(line):
            fail(path, i, "cross-reference uses a line number; use §<section> instead")


def main() -> int:
    files: list[Path] = []
    for target in TARGETS:
        if not target.exists():
            continue
        files += [p for p in sorted(target.rglob("*.md")) if p.parent.name not in SKIP_DIRS]

    if not files:
        print("  (no planning documents found)")
        return 0

    for path in files:
        lint(path)

    if problems:
        print(f"\n✗ {len(problems)} documentation problem(s):\n", file=sys.stderr)
        for p in problems:
            print(f"    {p}", file=sys.stderr)
        print(file=sys.stderr)
        return 1

    print(f"✓ {len(files)} document(s) conform to the template")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
