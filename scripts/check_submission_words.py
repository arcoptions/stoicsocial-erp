from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "project_submission"

WORD_RE = re.compile(r"\b[\w'-]+\b")

REQUIRED = {
    "01_project_title.md": (1, 120),
    "02_extended_abstract.md": (3000, 5000),
    "03_project_report.md": (15000, 30000),
}


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text))


def main() -> int:
    missing = [name for name in REQUIRED if not (DOCS / name).exists()]
    if missing:
        print("Missing required file(s):")
        for name in missing:
            print(f"- {name}")
        return 1

    failed = False
    print("Submission word-count validation")
    print("=" * 32)

    for name, (low, high) in REQUIRED.items():
        text = (DOCS / name).read_text(encoding="utf-8")
        wc = count_words(text)
        ok = low <= wc <= high
        status = "PASS" if ok else "FAIL"
        print(f"{name}: {wc} words | required {low}-{high} | {status}")
        if not ok:
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
