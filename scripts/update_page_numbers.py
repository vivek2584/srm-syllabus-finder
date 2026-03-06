#!/usr/bin/env python3
"""
update_page_numbers.py — Scan the PDF to find page boundaries for each course
and update the start_page / end_page columns in the existing database.
Run this instead of re-parsing everything from scratch.
"""

import re
import sqlite3
from pathlib import Path

ROOT     = Path(__file__).parent.parent
PDF_PATH = ROOT / "computing-programmes-syllabus-2021.pdf"
DB_PATH  = ROOT / "data" / "syllabi.db"

RE_CODE = re.compile(r'\b(21[A-Z]{2,5}\d{3}[A-Z]?)\b')
RE_LTPC = re.compile(r'\bL\s+T\s+P\s+C\b')


def main():
    if not PDF_PATH.exists():
        print(f"ERROR: PDF not found at {PDF_PATH}")
        return

    try:
        import pdfplumber
    except ImportError:
        print("pdfplumber not installed.")
        return

    print("Scanning PDF pages...")
    pages = []
    with pdfplumber.open(str(PDF_PATH)) as pdf:
        total = len(pdf.pages)
        print(f"  {total} pages total")
        for i, page in enumerate(pdf.pages):
            pages.append(page.extract_text() or "")

    print("Finding course boundaries...")
    starts = []
    for i, text in enumerate(pages):
        if not RE_LTPC.search(text):
            continue
        codes = RE_CODE.findall(text)
        if codes:
            starts.append((i, codes[0].upper()))

    print(f"  Found {len(starts)} course boundaries")

    # Add columns if missing
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("ALTER TABLE courses ADD COLUMN start_page INTEGER DEFAULT 0")
        print("  Added start_page column")
    except sqlite3.OperationalError:
        print("  start_page column already exists")
    try:
        conn.execute("ALTER TABLE courses ADD COLUMN end_page INTEGER DEFAULT 0")
        print("  Added end_page column")
    except sqlite3.OperationalError:
        print("  end_page column already exists")
    conn.commit()

    print("Updating page numbers in database...")
    updated = 0
    for idx, (si, code) in enumerate(starts):
        ei = starts[idx + 1][0] if idx + 1 < len(starts) else min(si + 5, len(pages))
        result = conn.execute(
            "UPDATE courses SET start_page=?, end_page=? WHERE UPPER(code)=?",
            (si, ei, code)
        )
        if result.rowcount > 0:
            updated += 1

    conn.commit()
    conn.close()

    print(f"Done! Updated {updated} courses with page numbers.")


if __name__ == "__main__":
    main()
