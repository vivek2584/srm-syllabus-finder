#!/usr/bin/env python3
"""
update_page_numbers.py — Scan a syllabus PDF to find page boundaries for each
course and update the start_page / end_page columns in the existing database.
Run this instead of re-parsing everything from scratch.

Usage:
    python scripts/update_page_numbers.py
    python scripts/update_page_numbers.py --pdf csbs-syllabus-2021.pdf
"""

import re
import argparse
import sqlite3
from pathlib import Path

ROOT        = Path(__file__).parent.parent
DB_PATH     = ROOT / "data" / "syllabi.db"
DEFAULT_PDF = "computing-programmes-syllabus-2021.pdf"

RE_CODE = re.compile(r'\b(21[A-Z]{2,5}\d{3}[A-Z]?)\b')
RE_LTPC = re.compile(r'\bL\s+T\s+P\s+C\b')


def main():
    ap = argparse.ArgumentParser(
        description="Update start_page/end_page for courses from a given syllabus PDF."
    )
    ap.add_argument(
        "--pdf",
        default=DEFAULT_PDF,
        help=f"PDF filename (relative to project root). Default: {DEFAULT_PDF}",
    )
    args = ap.parse_args()

    pdf_path = ROOT / args.pdf
    pdf_filename = pdf_path.name

    if not pdf_path.exists():
        print(f"ERROR: PDF not found at {pdf_path}")
        return

    try:
        import pdfplumber
    except ImportError:
        print("pdfplumber not installed.")
        return

    print(f"PDF: {pdf_filename}")
    print("Scanning PDF pages...")
    pages = []
    with pdfplumber.open(str(pdf_path)) as pdf:
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
    for col_def in [
        "ALTER TABLE courses ADD COLUMN start_page INTEGER DEFAULT 0",
        "ALTER TABLE courses ADD COLUMN end_page INTEGER DEFAULT 0",
        "ALTER TABLE courses ADD COLUMN source_pdf TEXT DEFAULT ''",
    ]:
        try:
            conn.execute(col_def)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()

    print("Updating page numbers in database...")
    updated = 0
    for idx, (si, code) in enumerate(starts):
        ei = starts[idx + 1][0] if idx + 1 < len(starts) else min(si + 5, len(pages))
        result = conn.execute(
            "UPDATE courses SET start_page=?, end_page=?, source_pdf=? WHERE UPPER(code)=?",
            (si, ei, pdf_filename, code)
        )
        if result.rowcount > 0:
            updated += 1

    conn.commit()
    conn.close()

    print(f"Done! Updated {updated} courses with page numbers from '{pdf_filename}'.")


if __name__ == "__main__":
    main()
