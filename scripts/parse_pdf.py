#!/usr/bin/env python3
"""
parse_pdf.py — Extract all course syllabi from an SRM syllabus PDF into SQLite.

Usage:
    python scripts/parse_pdf.py
    python scripts/parse_pdf.py --pdf csbs-syllabus-2021.pdf
    python scripts/parse_pdf.py --pdf csbs-syllabus-2021.pdf --skip-existing
    python scripts/parse_pdf.py --debug
"""

import sys
import os
import re
import json
import sqlite3
import argparse
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent.parent
DB_PATH    = ROOT / "data" / "syllabi.db"
SYLLABI_DIR = ROOT / "syllabi"          # folder for all syllabus PDFs
DEFAULT_PDF = "computing-programmes-syllabus-2021.pdf"

# ── Regex patterns ────────────────────────────────────────────────────────────
RE_CODE    = re.compile(r'\b(21[A-Z]{2,5}\d{3}[A-Z]?)\b')
RE_LTPC    = re.compile(r'\bL\s+T\s+P\s+C\b')
RE_CREDITS = re.compile(r'\b(\d)\s+(\d)\s+(\d)\s+(\d)\b')

# ── DB helpers ────────────────────────────────────────────────────────────────
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS courses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT    UNIQUE NOT NULL,
    name       TEXT    NOT NULL,
    category   TEXT    DEFAULT '',
    l          INTEGER DEFAULT 0,
    t          INTEGER DEFAULT 0,
    p          INTEGER DEFAULT 0,
    c          INTEGER DEFAULT 0,
    department TEXT    DEFAULT '',
    prereq     TEXT    DEFAULT 'Nil',
    coreq      TEXT    DEFAULT 'Nil',
    clrs       TEXT    DEFAULT '[]',
    cos        TEXT    DEFAULT '[]',
    units      TEXT    DEFAULT '[]',
    resources  TEXT    DEFAULT '[]',
    raw_text   TEXT    DEFAULT '',
    start_page INTEGER DEFAULT 0,
    end_page   INTEGER DEFAULT 0,
    source_pdf TEXT    DEFAULT ''
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
    # Add columns if they do not exist (migrations for older DBs)
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
    v = re.sub(r'(?:^|(?<=\s))[\d\-\']+(?:\s+[\d\-\']+){6,}', '', v)
    # Reversed-word garbage with & separators
    v = re.sub(r'\s+&\s+&.*$', '', v, flags=re.DOTALL)
    # Trailing orphan page numbers with optional slash (e.g. "...14 /")
    v = re.sub(r'\s+\d{1,3}\s*/?\s*$', '', v)
    # Character-spaced PO table noise (PDFs with spaced-out rotated headers):
    # e.g. "C C C C C L L L L o R R R R ur - - - - s 2 3 4 5"
    v = re.sub(r'(?:\b\S\s){4,}\S.*$', '', v, flags=re.DOTALL)
    return v.strip()


# ── PO score line patterns ────────────────────────────────────────────────────
# Matches a line that is ONLY PO scores / dashes / Outcomes header:
#   "1 2 3 4 5 6 7 8 9 10 11 12 Outcomes" or "3 - - 3 - - ..."
_RE_PO_ONLY_LINE = re.compile(
    r'^\s*(?:[\d\-]+\s+){3,}[\d\-]+(?:\s+(?:Outcomes?|PSO\d?))?\s*$'
)
# Matches PO scores appended inline at end of a CLR/CO text line:
#   "some text 1 2 3 4 5 6 7 8 9 10 11 12 Outcomes"
_RE_INLINE_PO = re.compile(
    r'\s+(?:\d+\s+){5,}\d+(?:\s+(?:Outcomes?|PSO\d?))?\s*$'
)


def _reconstruct_clr_co_text(section: str) -> str:
    """Pre-process CLR/CO section to fix two-column PDF layout artifacts.

    The PDF has two columns: (left) CLR/CO text, (right) PO score table.
    pdfplumber merges them producing these artifact patterns:

    Pattern A: PO scores inline at end of text line -> strip them.
    Pattern B: PO-only line between label and its text -> skip PO line.
    Pattern C: Bare label (no text after stripping PO scores) -> inline
               the next non-label line as the actual item text.
    """
    _RE_LABEL = re.compile(r'^\s*(CLR|CO)[-\s]*\d+\s*[:\-]', re.IGNORECASE)

    # Pass 1: strip PO score noise line-by-line
    lines = section.split('\n')
    pass1 = []
    for line in lines:
        if _RE_PO_ONLY_LINE.match(line):
            continue                    # drop PO-score-only lines
        cleaned = _RE_INLINE_PO.sub('', line).rstrip()
        pass1.append(cleaned)

    # Pass 2: for bare label lines (e.g. "CLR-2:" with no text after colon),
    # append the next non-empty, non-label line as the item text.
    result = []
    j = 0
    while j < len(pass1):
        line = pass1[j]
        result.append(line)
        stripped = line.strip()
        is_bare_label = (
            bool(_RE_LABEL.match(stripped))
            and len(stripped) < 12      # "CLR-2:" or "CO-4:" only (no body)
        )
        if is_bare_label:
            k = j + 1
            while k < len(pass1) and not pass1[k].strip():
                k += 1
            if k < len(pass1) and not _RE_LABEL.match(pass1[k].strip()):
                result[-1] = stripped + ' ' + pass1[k].strip()
                j = k + 1
                continue
        j += 1

    return '\n'.join(result)

def _strip_interitem_garbage(v: str) -> str:
    """Strip page-footer artifacts that get captured between CLR/CO items.

    When the PO score table is on the same page as a page break footer,
    pdfplumber inserts page numbers, '/', '&' fragments between items.
    E.g.: 'applications 327 / & & & CLR-3: ...' -> 'applications'
    """
    # Remove standalone page numbers (1-3 digit numbers on their own)
    v = re.sub(r'\s+\d{1,3}\s*$', '', v)
    v = re.sub(r'^\s*\d{1,3}\s+', '', v)
    # Remove lines that are only &, /, whitespace fragments
    lines = [ln for ln in v.split('\n')
             if re.search(r'[A-Za-z]{2,}', ln)]   # keep only lines with real words
    v = ' '.join(lines)
    # Strip residual &, /, single-char noise
    v = re.sub(r'(?<![A-Za-z])(&|/)(?![A-Za-z])', ' ', v)
    return v.strip()


def parse_clrs(text: str) -> list[str]:
    # Pre-process to remove PO column noise
    text = _reconstruct_clr_co_text(text)

    items = re.findall(
        r'CLR[-\s]*(\d+)\s*[:\-]\s*(.+?)(?=CLR[-\s]*\d+\s*[:\-]|Course Outcomes|CO[-\s]*\d+|$)',
        text, re.DOTALL | re.IGNORECASE
    )
    cleaned = []
    for n, v in items:
        v = v.strip()
        v = re.sub(r'^[\d\s\-\']{8,}(?:Outcomes?)?\s*', '', v)
        v = re.sub(
            r'(?:egdelwonK|gnireenignE|sisylanA|melborP|ngiseD|snoitulos'
            r'|snoitagitsevni|tcudnoC|smelborp|xelpmoc|egasU|looT|nredoM'
            r'|yteicos|tnemnorivnE|ytilibaniatsuS|scihtE|kroW|maeT'
            r'|laudividnI|noitacinummoC|ecnaniF|tcejorP|gninraeL|efiL'
            r'|1-OSP|2-OSP|3-OSP|fo|dna|ehT)[\s\n]+',
            ' ', v, flags=re.IGNORECASE
        )
        v = _strip_interitem_garbage(v)
        v = _strip_po_noise(v)
        v = ' '.join(v.split())
        if len(v) > 10:
            cleaned.append(f"CLR-{n}: {v}")

    # Join page-break continuations: only when the preceding entry body ends
    # with a function word (preposition, article, conjunction, auxiliary) OR
    # when the continuation is a single bare word/phrase with no verb — both
    # indicate a genuine mid-clause truncation at a page boundary.
    _TRUNCATED_TAIL = re.compile(
        r'\b(the|a|an|of|in|to|for|and|or|on|at|by|with|its|their|various|'
        r'different|certain|such|this|that|these|those|from|into|about|'
        r'between|through|using|under|over)$', re.IGNORECASE
    )
    _SINGLE_NOUN = re.compile(r'^\w+(?:\s+\w+){0,2}[,.]?$')  # 1-3 word bare phrase
    merged = []
    for entry in cleaned:
        body = entry.split(':', 1)[-1].strip()
        is_tail = _TRUNCATED_TAIL.search(merged[-1]) if merged else False
        is_bare = _SINGLE_NOUN.match(body) and len(body) < 20
        if merged and (is_tail and len(body) < 30) or (is_bare and is_tail):
            merged[-1] = merged[-1].rstrip('.') + ' ' + body
        elif merged and is_bare and len(body) <= 10:
            # Single very-short bare word — almost certainly a page-break tail
            merged[-1] = merged[-1].rstrip('.') + ' ' + body
        else:
            merged.append(entry)
    return merged


def parse_cos(text: str) -> list[str]:
    # Pre-process to remove PO column noise
    text = _reconstruct_clr_co_text(text)

    items = re.findall(
        r'\bCO[-\s]*(\d+)\s*[:\-]\s*(.+?)(?=\bCO[-\s]*\d+\s*[:\-]|Unit[-\s]*(?:\d+|I{1,3}V?|VI{0,3})\b|$)',
        text, re.DOTALL | re.IGNORECASE
    )
    cleaned = []
    for n, v in items:
        v = v.strip()
        v = re.sub(r'^[\d\s\-\']{8,}', '', v)
        v = re.sub(
            r'(?:egdelwonK|gnireenignE|sisylanA|melborP|ngiseD|snoitulos'
            r'|snoitagitsevni|tcudnoC|smelborp|xelpmoc|egasU|looT|nredoM'
            r'|yteicos|tnemnorivnE|ytilibaniatsuS|scihtE|kroW|maeT'
            r'|laudividnI|noitacinummoC|ecnaniF|tcejorP|gninraeL|efiL'
            r'|1-OSP|2-OSP|3-OSP|fo|dna|ehT)[\s\n]+',
            ' ', v, flags=re.IGNORECASE
        )
        v = _strip_interitem_garbage(v)
        v = _strip_po_noise(v)
        v = ' '.join(v.split())
        if len(v) > 10:
            cleaned.append(f"CO-{n}: {v}")

    # Join page-break continuations (same logic as parse_clrs)
    _TRUNCATED_TAIL = re.compile(
        r'\b(the|a|an|of|in|to|for|and|or|on|at|by|with|its|their|various|'
        r'different|certain|such|this|that|these|those|from|into|about|'
        r'between|through|using|under|over)$', re.IGNORECASE
    )
    _SINGLE_NOUN = re.compile(r'^\w+(?:\s+\w+){0,2}[,.]?$')
    merged = []
    for entry in cleaned:
        body = entry.split(':', 1)[-1].strip()
        is_tail = _TRUNCATED_TAIL.search(merged[-1]) if merged else False
        is_bare = _SINGLE_NOUN.match(body) and len(body) < 20
        if merged and (is_tail and len(body) < 30) or (is_bare and is_tail):
            merged[-1] = merged[-1].rstrip('.') + ' ' + body
        elif merged and is_bare and len(body) <= 10:
            merged[-1] = merged[-1].rstrip('.') + ' ' + body
        else:
            merged.append(entry)
    return merged


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
    # Map Roman numeral unit numbers to int
    _ROMAN = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5,
              'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10}
    _UNIT_NUM = r'(?:(\d+)|(I{1,3}V?|VI{0,3}|IX|IV|VIII|VII|VI|V|IV|III|II|I))'

    # Boundary pattern shared by both primary and fallback regexes
    _UNIT_END = r'(?=Unit[-\s]*(?:\d+|I{1,3}V?|VI{0,3}|IX)\s*[-–:]|Learning\s*\n?\s*Resources|Learning\s+Assessment|$)'

    # Title-less pattern (match FIRST): "Unit-1 - 9 Hour" or "Unit-I - 9 Hour"
    pattern_notitle = re.compile(
        r'Unit[-\s]*' + _UNIT_NUM + r'\s*[-–:]\s*(\d+)\s*Hours?\b(.*?)'
        + _UNIT_END,
        re.DOTALL | re.IGNORECASE
    )
    # Titled pattern: "Unit-1 - Title  12 Hour(s)" or "Unit-I: Title  9 hours"
    pattern_titled = re.compile(
        r'Unit[-\s]*' + _UNIT_NUM + r'\s*[-–:]\s*(.+?)\s+(\d+)\s*Hours?\b(.*?)'
        + _UNIT_END,
        re.DOTALL | re.IGNORECASE
    )
    units = []
    matched = set()

    def _unit_num(arabic, roman):
        if arabic:
            return int(arabic)
        return _ROMAN.get(roman.upper(), 0)


    # Pass 1: match title-less units first ("Unit-1 - 9 Hour\ncontent...")
    for m in pattern_notitle.finditer(text):
        arabic, roman, hours_str, content = m.group(1), m.group(2), m.group(3), m.group(4)
        n = _unit_num(arabic, roman)
        if not n or n in matched:
            continue
        content_text = content.strip()
        lines = content_text.split('\n') if content_text else []
        first_line = lines[0].strip() if lines else ''
        if first_line and len(first_line) < 80 and not re.match(r'^\d', first_line):
            title = first_line
            content_text = '\n'.join(lines[1:]).strip()
        elif first_line:
            topic = re.split(r'\s*[-:;,]\s*', first_line)[0].strip()
            topic = topic.rstrip('\u2014\u2013-').strip()
            title = topic if (topic and 3 < len(topic) < 80) else f"Unit {n}"
        else:
            title = f"Unit {n}"
        units.append({"number": n, "title": title, "hours": int(hours_str),
                      "content": _clean_unit_content(content_text)})
        matched.add(n)

    # Pass 2: match titled units ("Unit-1 - Some Title 12 Hour\ncontent...")
    for m in pattern_titled.finditer(text):
        arabic, roman, title, hours, content = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        n = _unit_num(arabic, roman)
        if not n or n in matched:
            continue
        title = title.strip()
        if '\n' in title:
            parts = title.split('\n', 1)
            title = parts[0].strip()
            content = parts[1].strip() + '\n' + content
        if re.match(r'^\d+$', title):
            first_line = content.strip().split('\n')[0].strip() if content.strip() else ''
            if first_line and len(first_line) < 100 and not re.match(r'^\d', first_line):
                title = first_line
                content = '\n'.join(content.strip().split('\n')[1:]).strip()
            else:
                title = f"Unit {n}"
        units.append({"number": n, "title": title, "hours": int(hours),
                      "content": _clean_unit_content(content.strip())})
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
    both columns into single lines, causing:
      - Entry 1 (left col) and Entry 4 (right col) merged on the same line
      - Entry continuation on the next line
      - Lab Experiments sub-section using the same numbered format
      - Words split across lines by hyphenation

    Strategy:
    1. Locate the resources section (after last Unit, before Learning Assessment)
    2. Skip any Lab Experiments sub-section
    3. Flatten the section and split on ALL numbered markers (including inline ones)
    4. Clean each entry individually
    """
    # 1. Locate the resources section
    last_unit = None
    for u in (5, 4, 3):
        matches = list(re.finditer(rf'Unit[-\s]*{u}\s*[-\u2013:]', text, re.IGNORECASE))
        if matches:
            last_unit = matches[-1]
            break
    start = last_unit.start() if last_unit else 0

    end_markers = list(re.finditer(
        r'(Learning\s+Assessment|Course\s+Designers)',
        text[start:], re.IGNORECASE
    ))
    end = start + end_markers[0].start() if end_markers else len(text)
    section = text[start:end]

    # 2. Skip Lab Experiments sub-section
    # Lab experiments appear right after Unit-5 content and before book references.
    # Detect the first real publisher/author keyword to mark where books start.
    PUBLISHER_PAT = re.compile(
        r'(?:Wiley|Pearson|Springer|McGraw|Prentice|Tata|Oxford|Cambridge|CRC|Elsevier'
        r'|PHI|Apress|O.Reilly|O\'Reilly|Morgan|Addison|Chapman|Cengage|Packt'
        r'|Press\b|Edition\b|Publication|ISBN)',
        re.IGNORECASE
    )
    pub_match = PUBLISHER_PAT.search(section)
    if pub_match:
        # Walk backwards from first publisher to find a numbered entry start
        pre = section[:pub_match.start()]
        lab_hdr = re.search(r'\bLab\s+Experiments?\b', pre, re.IGNORECASE)
        if lab_hdr:
            # Find the numbered entry that contains/precedes the publisher match
            num_before = list(re.finditer(r'(?<!\d)(\d+)\.\s+[A-Z]', section[:pub_match.start() + 50]))
            if num_before:
                section = section[num_before[-1].start():]

    # 3. Flatten: join continuation lines (lines that don't start with a number)
    #    but keep newlines that separate entries.
    # First, replace newlines that split mid-word (lower-case start after alpha end)
    section = re.sub(r'(?<=[A-Za-z])\n(?=[a-z])', '', section)
    # Then, join other continuation lines (non-numbered) to the previous line
    lines = section.split('\n')
    joined_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if re.match(r'^\d+\.', line) or not joined_lines:
            joined_lines.append(line)
        else:
            joined_lines[-1] += ' ' + line

    # 4. Re-flatten into a single string and extract all numbered entries
    flat = ' '.join(joined_lines)
    # Split on numbered markers (handles inline: "...Press. 4. Next Author...")
    raw_entries = re.split(r'(?<!\d)\b(\d+)\.\s+', flat)

    # raw_entries alternates: [pre_text, num, body, num, body, ...]
    entries: list[tuple[int, str]] = []
    i = 1
    while i + 1 < len(raw_entries):
        try:
            num = int(raw_entries[i])
            body = raw_entries[i + 1].strip()
            entries.append((num, body))
        except (ValueError, IndexError):
            pass
        i += 2

    # 5. Clean and filter
    _RE_LAB_TASK = re.compile(
        r'^(Implement\b|Design\b|Study\b|Configure\b|Install\b|Build\b|Develop\b'
        r'|Test\b|Create\b|Simulate\b|Analyze\b|Lab\s+Experiments?'
        r'|Unit[-\s]*\d|Course\s+Offering|Learning\b|Resources\b)',
        re.IGNORECASE
    )

    results = []
    seen: set[str] = set()

    for num, body in sorted(entries, key=lambda x: x[0]):
        clean = _sanitize_resource(body)

        # Skip lab tasks and headers
        if _RE_LAB_TASK.match(clean):
            continue
        # Skip too short
        if len(clean) < 15:
            continue
        # Deduplicate
        key = clean[:40].lower()
        if key in seen:
            continue
        seen.add(key)

        # URL entries
        if clean.startswith('http'):
            results.append(clean)
            continue

        # Must start with uppercase (author/title)
        if not clean[0].isupper() and not clean[0].isdigit():
            continue

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
def run(pdf_path: Path = None, skip_existing: bool = False, debug: bool = False):
    if pdf_path is None:
        pdf_path = ROOT / DEFAULT_PDF

    if not pdf_path.exists():
        sys.exit(f"PDF not found at {pdf_path}")

    pdf_filename = pdf_path.name
    insert_sql = (
        "INSERT OR IGNORE" if skip_existing else "INSERT OR REPLACE"
    )

    print(f"PDF: {pdf_filename}")
    if skip_existing:
        print("  Mode: --skip-existing (existing courses will NOT be overwritten)")

    print("Step 1/4 — Extracting pages from PDF ...")
    pages = extract_pages(pdf_path, verbose=not debug)

    print("Step 2/4 — Finding course boundaries ...")
    starts = find_course_starts(pages)
    print(f"  Found {len(starts)} courses")

    if debug:
        print("\n=== DEBUG: First 3 course blocks ===")
        for i in range(min(3, len(starts))):
            si, code = starts[i]
            ei = starts[i + 1][0] if i + 1 < len(starts) else si + 4
            block = "\n".join(pages[si:ei])
            print(f"\n--- Course {code} (pages {si}\u2013{ei}) ---")
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
                f"""{insert_sql} INTO courses
                   (code, name, category, l, t, p, c, department, prereq, coreq,
                    clrs, cos, units, resources, raw_text, start_page, end_page,
                    source_pdf)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data["code"], data["name"], data["category"],
                    data["l"], data["t"], data["p"], data["c"],
                    data["department"], data["prereq"], data["coreq"],
                    json.dumps(data["clrs"]),  json.dumps(data["cos"]),
                    json.dumps(data["units"]), json.dumps(data["resources"]),
                    data["raw_text"], si, ei,
                    pdf_filename
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
    ap = argparse.ArgumentParser(
        description="Extract SRM syllabus courses from a PDF into SQLite."
    )
    ap.add_argument(
        "--pdf",
        default=None,
        help="PDF filename (relative to project root or syllabi/ dir). "
             f"Default: {DEFAULT_PDF}",
    )
    ap.add_argument(
        "--pdf-dir",
        default=None,
        metavar="DIR",
        help="Parse ALL *.pdf files in this directory (relative to project root). "
             "Uses --skip-existing automatically.",
    )
    ap.add_argument(
        "--skip-existing",
        action="store_true",
        help="Use INSERT OR IGNORE so existing course records are not overwritten.",
    )
    ap.add_argument(
        "--debug",
        action="store_true",
        help="Print sample extraction and exit without writing to DB.",
    )
    args = ap.parse_args()

    if args.pdf_dir:
        # Batch mode: parse every PDF in the given directory
        pdf_dir = ROOT / args.pdf_dir
        if not pdf_dir.is_dir():
            sys.exit(f"Directory not found: {pdf_dir}")
        pdfs = sorted(pdf_dir.glob("*.pdf"))
        if not pdfs:
            sys.exit(f"No PDFs found in {pdf_dir}")
        print(f"Batch mode: {len(pdfs)} PDFs in {pdf_dir}")
        for pdf_path in pdfs:
            print(f"\n{'='*60}")
            run(pdf_path=pdf_path, skip_existing=True, debug=args.debug)
        print(f"\nBatch complete. {len(pdfs)} PDFs processed.")
    else:
        # Single-file mode
        if args.pdf is None:
            # Default: check syllabi/ dir first, then root
            default_path = SYLLABI_DIR / DEFAULT_PDF
            if not default_path.exists():
                default_path = ROOT / DEFAULT_PDF
        else:
            # Search syllabi/ first, then root
            candidate = SYLLABI_DIR / args.pdf
            default_path = candidate if candidate.exists() else ROOT / args.pdf
        run(pdf_path=default_path, skip_existing=args.skip_existing, debug=args.debug)
