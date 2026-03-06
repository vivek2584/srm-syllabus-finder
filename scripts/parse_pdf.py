#!/usr/bin/env python3
"""
parse_pdf.py — Extract all course syllabi from the SRM PDF into SQLite.

Usage:
    python scripts/parse_pdf.py
    python scripts/parse_pdf.py --debug   # prints sample extraction to stdout
"""

import sys
import os
import re
import json
import sqlite3
import argparse
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
PDF_PATH  = ROOT / "computing-programmes-syllabus-2021.pdf"
DB_PATH   = ROOT / "data" / "syllabi.db"

# ── Regex patterns ────────────────────────────────────────────────────────────
RE_CODE    = re.compile(r'\b(21[A-Z]{2,5}\d{3}[A-Z]?)\b')
RE_LTPC    = re.compile(r'\bL\s+T\s+P\s+C\b')
RE_CREDITS = re.compile(r'\b(\d)\s+(\d)\s+(\d)\s+(\d)\b')

# ── DB helpers ────────────────────────────────────────────────────────────────
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS courses (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    code      TEXT    UNIQUE NOT NULL,
    name      TEXT    NOT NULL,
    category  TEXT    DEFAULT '',
    l         INTEGER DEFAULT 0,
    t         INTEGER DEFAULT 0,
    p         INTEGER DEFAULT 0,
    c         INTEGER DEFAULT 0,
    department TEXT   DEFAULT '',
    prereq    TEXT    DEFAULT 'Nil',
    coreq     TEXT    DEFAULT 'Nil',
    clrs      TEXT    DEFAULT '[]',
    cos       TEXT    DEFAULT '[]',
    units     TEXT    DEFAULT '[]',
    resources TEXT    DEFAULT '[]',
    raw_text  TEXT    DEFAULT '',
    start_page INTEGER DEFAULT 0,
    end_page   INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_code ON courses(code);
CREATE INDEX IF NOT EXISTS idx_name ON courses(name);
"""

def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    for stmt in CREATE_SQL.strip().split(";"):
        if stmt.strip():
            conn.execute(stmt)
    # Add columns if they do not exist
    try:
        conn.execute("ALTER TABLE courses ADD COLUMN start_page INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE courses ADD COLUMN end_page INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass # Already created
    conn.commit()
    return conn


# ── PDF extraction ────────────────────────────────────────────────────────────
def extract_pages(pdf_path: Path, verbose: bool = True) -> list[str]:
    try:
        import pdfplumber
    except ImportError:
        sys.exit("pdfplumber not installed. Run: pip install pdfplumber")

    pages = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        total = len(pdf.pages)
        if verbose:
            print(f"  PDF loaded — {total} pages")
        for i, page in enumerate(pdf.pages):
            if verbose and i % 100 == 0:
                print(f"  Extracting page {i}/{total} ...")
            pages.append(page.extract_text() or "")
    return pages


# ── Course boundary detection ─────────────────────────────────────────────────
def find_course_starts(pages: list[str]) -> list[tuple[int, str]]:
    """
    Return list of (page_index, course_code) for every course start page.
    A course start page has 'L T P C' header AND a course code.
    """
    starts = []
    for i, text in enumerate(pages):
        if not RE_LTPC.search(text):
            continue
        codes = RE_CODE.findall(text)
        if codes:
            starts.append((i, codes[0]))
    return starts


# ── Text cleaning ────────────────────────────────────────────────────────────
# Reversed PO-column header words that pdfplumber extracts from sideways text
_ROTATED_WORDS = re.compile(
    r'\b(?:egdelwonK|gnireenignE|sisylanA|melborP|tnempoleved|ngiseD'
    r'|snoitulos|snoitagitsevni|tcudnoC|smelborp|xelpmoc|egasU|looT'
    r'|nredoM|reenigne|yteicos|tnemnorivnE|ytilibaniatsuS|scihtE'
    r'|kroW|maeT|laudividnI|noitacinummoC|ecnaniF|tcejorP|gninraeL'
    r'|efiL|gnoL|ehT|dna|fo'       # ← added short reversed words
    r'|1-OSP|2-OSP|3-OSP)\b'
)
# Page footer pattern
_PAGE_FOOTER = re.compile(
    r'B\.Tech\s*/\s*M\.Tech.*?Control Copy', re.DOTALL
)
# PO matrix number row: "1 2 3 4 5 6 7 8 9 10 11 12"
_PO_HEADER = re.compile(r'(?:^|\n)\s*(?:\d+\s+){5,}\d+\s*(?:Outcomes?|$)', re.MULTILINE)
# Trailing PO scores on a CO/CLR line: " 3 2 - - - - 1 - -"
_TRAILING_SCORES = re.compile(r'[\s\d\-]{12,}$')
# Remaining reversed-word garbage (short fragments with & separators)
_GARBAGE_FRAG = re.compile(r'\s+(?:&\s*){2,}.{0,50}$')


def clean_text(text: str) -> str:
    """Remove PDF layout artefacts before parsing."""
    text = _PAGE_FOOTER.sub(' ', text)
    text = _ROTATED_WORDS.sub(' ', text)
    text = re.sub(r'\.tgM\b', ' ', text)           # reversed "Mgmt."
    text = _PO_HEADER.sub('\n', text)
    # Collapse excessive whitespace / blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


# ── Text-block parsers ────────────────────────────────────────────────────────
def _first_nonempty(lines, default=""):
    for l in lines:
        s = l.strip()
        if s:
            return s
    return default


_CATEGORY_SUFFIXES = [
    " E PROFESSIONAL ELECTIVE", " C PROFESSIONAL CORE",
    " S ENGINEERING SCIENCES", " PROFESSIONAL ELECTIVE",
    " PROFESSIONAL CORE", " ENGINEERING SCIENCES",
]


def parse_name(text: str, code: str) -> str:
    """
    The course name appears in a two-row table header in the PDF:

      Row 1:  Course  Course  <NAME PART 1>              Course  L T P C
      Row 3:  Code    Name    <NAME PART 2 (overflow)>   Category  ...

    pdfplumber flattens these into consecutive lines.  We first try to grab the
    name from the code's line (row 1), then check the "Code Name" line (row 3)
    for any overflow continuation.
    """
    # ── Part 1: extract name from the line containing the course code ──
    # Try: '<CODE>   SOME NAME   C   PROFESSIONAL CORE'
    # Allow lowercase to capture 'IoT' etc.
    m = re.search(
        rf'{re.escape(code)}\s+([A-Za-z][A-Za-z0-9 ,()&/:;\-]+?)'
        r'(?:\s{2,}|\s+[A-Z]\s+(?:PROFESSIONAL|ENGINEERING|BASIC|HUMANITIES|MANAGEMENT|PROJECT))',
        text
    )
    if m:
        name = m.group(1).strip()
    else:
        # Fallback: take text after code until end-of-line
        m2 = re.search(rf'{re.escape(code)}\s+(.+)', text)
        if m2:
            name = m2.group(1).split("  ")[0].strip()
            # Remove trailing single letter (category code)
            name = re.sub(r'\s+[A-Z]$', '', name).strip()
        else:
            return ""

    # Strip trailing category suffix that leaked into the name
    upper = name.upper()
    for suf in _CATEGORY_SUFFIXES:
        if upper.endswith(suf):
            name = name[:len(name) - len(suf)].strip()
            break

    # If name is empty or just a category code, try extracting from surrounding text
    if not name or name.upper() in ("E", "C", "S", "PROFESSIONAL ELECTIVE",
                                     "PROFESSIONAL CORE", "ENGINEERING SCIENCES"):
        # Look for text between "Course" headers around the code line
        m3 = re.search(
            r'(?:Course\s+)?(?:Course\s+)?(.+?)\s+(?:Course\s+)?L\s+T\s+P\s+C',
            text[:500], re.IGNORECASE
        )
        if m3:
            candidate = m3.group(1).strip()
            # Remove header words
            candidate = re.sub(r'\bCourse\b', '', candidate).strip()
            candidate = re.sub(r'\s{2,}', ' ', candidate).strip()
            if len(candidate) > 5:
                name = candidate

    # ── Part 2: check for multi-line name continuation ──
    # The "Code Name <OVERFLOW> Category" line may contain the rest of the name.
    # When the name fits on one line, this row is just "Code Name Category 3 0 2 4"
    # so we must not capture "Category" itself as a continuation.
    cont_m = re.search(
        r'Code\s+Name\s+(?!Category\b)([A-Za-z][A-Za-z0-9 ,()&/:;\-]+?)\s+Category\b',
        text[:600]
    )
    if not cont_m:
        cont_m = re.search(
            r'Code\s+Name\s+(?!Category\b)([A-Za-z][A-Za-z0-9 ,()&/:;\-]+?)(?:\s{2,}|\s*\n)',
            text[:600]
        )
    if cont_m:
        continuation = cont_m.group(1).strip()
        if (continuation and len(continuation) > 1
                and continuation.upper() not in ("CODE", "NAME", "CATEGORY", "NIL")):
            name = name + " " + continuation

    return name


def parse_category(text: str) -> str:
    for cat in [
        "PROFESSIONAL CORE", "PROFESSIONAL ELECTIVE",
        "ENGINEERING SCIENCES", "BASIC SCIENCES",
        "HUMANITIES", "MANAGEMENT SCIENCES",
        "EMPLOYABILITY ENHANCEMENT", "PROJECT",
    ]:
        if cat in text.upper():
            return cat.title()
    return ""


def parse_ltpc(text: str, window: int = 800) -> tuple[int, int, int, int]:
    """Find the LTPC credits from the first table area of the block."""
    snippet = text[:window]
    for m in RE_CREDITS.finditer(snippet):
        l, t, p, c = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        # Sanity check — typical values
        if l <= 5 and t <= 3 and p <= 6 and c <= 8:
            return l, t, p, c
    return 0, 0, 0, 0


def parse_field(text: str, label: str) -> str:
    """Extract the value after a label like 'Pre-requisite'."""
    m = re.search(rf'{re.escape(label)}\s*[:\-]?\s*([^\n]+)', text, re.IGNORECASE)
    if not m:
        return "Nil"
    val = m.group(1).strip()
    # Stop at secondary fields that appear on the same line (common in SRM PDFs)
    for stopper in ("Data Book", "Co-", "Progressive", "Course Offering"):
        if stopper in val:
            val = val[:val.index(stopper)].strip()
    return val or "Nil"


def _strip_po_noise(v: str) -> str:
    """Remove PO matrix fragments that bleed into CLR/CO text."""
    # Remove inline PO number sequences (e.g. "1 2 3 4 5 6 7 8 9 10 11 12")
    v = re.sub(r'\s+\d(?:\s+\d+){5,}(?:\s*Outcomes?)?', '', v)
    # Remove PO score rows (sequences of digits/dashes like "3 2 - - - - - - - - - - 1 - -")
    # Use targeted removal — do NOT use .*$ as it destroys text after scores
    v = re.sub(r'(?:^|(?<=\s))[\d\-\']+(?:\s+[\d\-\']+){6,}', '', v)
    # Reversed-word garbage with & separators
    v = re.sub(r'\s+&\s+&.*$', '', v, flags=re.DOTALL)
    # Trailing orphan page numbers with optional slash (e.g. "...14 /")
    v = re.sub(r'\s+\d{1,3}\s*/?\s*$', '', v)
    return v.strip()


def parse_clrs(text: str) -> list[str]:
    items = re.findall(
        r'CLR[-\s]*(\d+)\s*[:\-]\s*(.+?)(?=CLR[-\s]*\d+\s*[:\-]|Course Outcomes|CO[-\s]*\d+|$)',
        text, re.DOTALL | re.IGNORECASE
    )
    cleaned = []
    for n, v in items:
        v = v.strip()
        # Strip leading PO matrix scores if they appear right after the label
        v = re.sub(r'^[\d\s\-]{8,}(?:Outcomes?)?\s*', '', v)
        v = _strip_po_noise(v)
        v = ' '.join(v.split())   # collapse whitespace
        if len(v) > 10:
            cleaned.append(f"CLR-{n}: {v}")
    return cleaned


def parse_cos(text: str) -> list[str]:
    items = re.findall(
        r'\bCO[-\s]*(\d+)\s*[:\-]\s*(.+?)(?=\bCO[-\s]*\d+\s*[:\-]|Unit[-\s]*1\b|$)',
        text, re.DOTALL | re.IGNORECASE
    )
    cleaned = []
    for n, v in items:
        v = v.strip()
        # Strip leading PO scores that appear right after the label
        v = re.sub(r'^[\d\s\-\']{8,}', '', v)
        v = _strip_po_noise(v)
        v = ' '.join(v.split())
        if len(v) > 10:
            cleaned.append(f"CO-{n}: {v}")
    return cleaned


def _clean_unit_content(content: str) -> str:
    """Strip learning-resources, assessment tables, and course-designer bleed
    from the end of unit content."""
    # Cut at the first occurrence of any end-of-syllabus marker
    end_markers = [
        r'\b\d+\.\s+[A-Z][a-z]+\s+[A-Z].*?(?:Press|Edition|Publishing|McGraw|Pearson|Wiley|Springer|Prentice|Elsevier|Cambridge|Oxford|CRC|PHI|Tata)',
        r'\b\d+\.\s+https?://',                        # numbered URL resources
        r'Learning\s*\n?\s*Resources',                  # split-line "Learning\nResources"
        r'\bLearning\s+Assessment\b',
        r'\bCourse\s+Designers?\b',
        r'\bBloom.{0,5}s?\s+(Level|Final)',
        r'\bCLA[-\s]*[12]\b',
        r'\bFormative\b.*\bSummative\b',
        r'\bLevel\s+\d\s+Remember\b',
        r'\bweightage\b',
        r'\bExperts\s+from\s+',
    ]
    combined = '|'.join(f'({p})' for p in end_markers)
    m = re.search(combined, content, re.IGNORECASE | re.DOTALL)
    if m:
        content = content[:m.start()]
    # Also remove trailing "Lab Experiments" header if it's orphaned at the very end
    # (lab listings that follow are fine; only strip if nothing follows)
    content = re.sub(r'\s*Lab\s+Experiments\s*$', '', content, flags=re.IGNORECASE)
    return content.strip()


def parse_units(text: str) -> list[dict]:
    # Boundary pattern shared by both primary and fallback regexes
    _UNIT_END = r'(?=Unit[-\s]*\d\s*[-–:]|Learning\s*\n?\s*Resources|Learning\s+Assessment|$)'

    # Title-less pattern (match FIRST): "Unit-1 - 9 Hour"  (no title, just hours)
    pattern_notitle = re.compile(
        r'Unit[-\s]*(\d)\s*[-–:]\s*(\d+)\s*Hours?\b(.*?)'
        + _UNIT_END,
        re.DOTALL | re.IGNORECASE
    )
    # Titled pattern: "Unit-1 - Title  12 Hour(s)"  (title present)
    pattern_titled = re.compile(
        r'Unit[-\s]*(\d)\s*[-–:]\s*(.+?)\s+(\d+)\s*Hours?\b(.*?)'
        + _UNIT_END,
        re.DOTALL | re.IGNORECASE
    )
    units = []
    matched = set()

    # Pass 1: match title-less units first ("Unit-1 - 9 Hour\ncontent...")
    for m in pattern_notitle.finditer(text):
        n = int(m.group(1))
        hours_str, content = m.group(2), m.group(3)
        if n not in matched:
            # Derive a title from the first line of content
            content_text = content.strip()
            lines = content_text.split('\n') if content_text else []
            first_line = lines[0].strip() if lines else ''
            # Use first line as title if it's a short standalone line
            if first_line and len(first_line) < 80 and not re.match(r'^\d', first_line):
                title = first_line
                content_text = '\n'.join(lines[1:]).strip()
            elif first_line:
                # Try to extract topic name from the start of content
                # Split on common delimiters: - : ; ,
                topic = re.split(r'\s*[-:;,]\s*', first_line)[0].strip()
                # Clean trailing em-dash variants
                topic = topic.rstrip('\u2014\u2013-').strip()
                if topic and len(topic) > 3 and len(topic) < 80:
                    title = topic
                else:
                    title = f"Unit {n}"
            else:
                title = f"Unit {n}"
            units.append({
                "number": n,
                "title":  title,
                "hours":  int(hours_str),
                "content": _clean_unit_content(content_text)
            })
            matched.add(n)

    # Pass 2: match titled units ("Unit-1 - Some Title 12 Hour\ncontent...")
    for m in pattern_titled.finditer(text):
        num, title, hours, content = m.groups()
        n = int(num)
        if n not in matched:
            title = title.strip()
            # If title contains newlines, the part after the first newline is content
            if '\n' in title:
                parts = title.split('\n', 1)
                title = parts[0].strip()
                content = parts[1].strip() + '\n' + content
            # If after cleanup the "title" is just a number (orphan hours
            # grabbed by the regex), derive from content
            if re.match(r'^\d+$', title):
                first_line = content.strip().split('\n')[0].strip() if content.strip() else ''
                if first_line and len(first_line) < 100 and not re.match(r'^\d', first_line):
                    title = first_line
                    content = '\n'.join(content.strip().split('\n')[1:]).strip()
                else:
                    title = f"Unit {n}"
            units.append({
                "number": n,
                "title":  title,
                "hours":  int(hours),
                "content": _clean_unit_content(content.strip())
            })
            matched.add(n)

    units.sort(key=lambda u: u["number"])
    return units


def _sanitize_resource(text: str) -> str:
    """Clean unicode artifacts from resource strings."""
    text = text.replace('\u2015', '"')   # ― → "
    text = text.replace('\u01c1', '"')   # ǁ → "
    text = text.replace('\u2014', '-')   # — → -
    text = text.replace('\u2013', '-')   # – → -
    text = text.replace('\u201c', '"')   # " → "
    text = text.replace('\u201d', '"')   # " → "
    text = text.replace('\u2018', "'")   # ' → '
    text = text.replace('\u2019', "'")   # ' → '
    # Collapse whitespace
    text = ' '.join(text.split())
    return text.strip().rstrip(" \t,.")


def parse_resources(text: str) -> list[str]:
    """
    Learning Resources appear in a two-column PDF table.  pdfplumber flattens
    this so the header "Learning Resources" gets split across lines ('Learning'
    on one line, 'Resources' on the next) and the numbered references are
    interleaved with those fragments.

    Strategy: find the region after the last unit block and before
    "Learning Assessment" / "Course Designers", then collect all numbered
    entries that look like academic references or URLs.
    """
    # Locate the end of the last unit (try 5, then 4, then 3)
    last_unit = None
    for u in (5, 4, 3):
        matches = list(re.finditer(rf'Unit[-\s]*{u}\s*[-–:]', text, re.IGNORECASE))
        if matches:
            last_unit = matches[-1]
            break
    start = last_unit.start() if last_unit else 0

    # Find the end boundary
    end_markers = list(re.finditer(
        r'(Learning\s+Assessment|Course\s+Designers)',
        text[start:], re.IGNORECASE
    ))
    end = start + end_markers[0].start() if end_markers else len(text)

    section = text[start:end]

    # Match numbered entries: "1. Author, Title, Publisher, Year" or "1. https://..."
    raw = re.findall(r'\b\d+\.\s+([A-Z][^0-9\n]{10,}|https?://[^\s\n]+)', section)
    results = []
    for item in raw:
        clean = _sanitize_resource(item)
        # Ignore very short or obviously wrong entries
        if len(clean) > 15 and not re.match(r'^(Lab|Unit|Course\s+Offering|Learning)', clean, re.IGNORECASE):
            results.append(clean)
        elif clean.startswith('http') and len(clean) > 10:
            results.append(clean)
    return results


def parse_block(text: str, code: str) -> dict:
    cleaned = clean_text(text)   # remove PDF artefacts before parsing
    name = parse_name(cleaned, code)
    cat  = parse_category(cleaned)
    l, t, p, c = parse_ltpc(cleaned)

    return {
        "code":       code,
        "name":       name,
        "category":   cat,
        "l": l, "t": t, "p": p, "c": c,
        "department": parse_field(cleaned, "Course Offering Department"),
        "prereq":     parse_field(cleaned, "Pre-requisite"),
        "coreq":      parse_field(cleaned, "Co-requisite"),
        "clrs":       parse_clrs(cleaned),
        "cos":        parse_cos(cleaned),
        "units":      parse_units(cleaned),
        "resources":  parse_resources(text),   # use original for resources (needs raw numbers)
        "raw_text":   text,
    }


# ── Main pipeline ─────────────────────────────────────────────────────────────
def run(debug: bool = False):
    if not PDF_PATH.exists():
        sys.exit(f"PDF not found at {PDF_PATH}")

    print("Step 1/4 — Extracting pages from PDF ...")
    pages = extract_pages(PDF_PATH, verbose=not debug)

    print("Step 2/4 — Finding course boundaries ...")
    starts = find_course_starts(pages)
    print(f"  Found {len(starts)} courses")

    if debug:
        print("\n=== DEBUG: First 3 course blocks ===")
        for i in range(min(3, len(starts))):
            si, code = starts[i]
            ei = starts[i + 1][0] if i + 1 < len(starts) else si + 4
            block = "\n".join(pages[si:ei])
            print(f"\n--- Course {code} (pages {si}–{ei}) ---")
            print(block[:2000])
        return

    print("Step 3/4 — Parsing course data ...")
    conn = init_db(DB_PATH)
    ok = 0
    skip = 0
    for idx, (si, code) in enumerate(starts):
        ei = starts[idx + 1][0] if idx + 1 < len(starts) else min(si + 5, len(pages))
        block = "\n".join(pages[si:ei])
        data  = parse_block(block, code)

        try:
            conn.execute(
                """INSERT OR REPLACE INTO courses
                   (code, name, category, l, t, p, c, department, prereq, coreq,
                    clrs, cos, units, resources, raw_text, start_page, end_page)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data["code"], data["name"], data["category"],
                    data["l"], data["t"], data["p"], data["c"],
                    data["department"], data["prereq"], data["coreq"],
                    json.dumps(data["clrs"]),  json.dumps(data["cos"]),
                    json.dumps(data["units"]), json.dumps(data["resources"]),
                    data["raw_text"], si, ei
                )
            )
            ok += 1
        except Exception as e:
            print(f"  SKIP {code}: {e}")
            skip += 1

        if (idx + 1) % 50 == 0:
            conn.commit()
            print(f"  Processed {idx + 1}/{len(starts)} ...")

    conn.commit()
    conn.close()

    print(f"Step 4/4 — Done.  {ok} courses saved, {skip} skipped.")
    print(f"  Database: {DB_PATH}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true", help="Print sample extraction and exit")
    args = ap.parse_args()
    run(debug=args.debug)
