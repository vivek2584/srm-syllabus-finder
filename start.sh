#!/usr/bin/env bash
# start.sh — one-command launcher for SRM Syllabus Finder
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv"
DB="$ROOT/data/syllabi.db"
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"

echo "=== SRM Syllabus Finder ==="

# 1) Create virtual environment if needed
if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV"
fi

# 2) Install dependencies
echo "Checking dependencies..."
"$PIP" install -q -r "$ROOT/requirements.txt"

# 3) Parse PDF → DB (only if DB doesn't exist yet)
if [ ! -f "$DB" ]; then
  echo ""
  echo "Database not found. Parsing PDF — this runs once and takes a few minutes..."
  "$PYTHON" "$ROOT/scripts/parse_pdf.py"
fi

# 3a) Parse CSBS PDF if it exists and wasn't already loaded
CSBS_PDF="$ROOT/csbs-syllabus-2021.pdf"
if [ -f "$CSBS_PDF" ]; then
  CSBS_COUNT=$(python3 -c "
import sqlite3
try:
    conn = sqlite3.connect('$DB')
    n = conn.execute(\"SELECT COUNT(*) FROM courses WHERE source_pdf='csbs-syllabus-2021.pdf'\").fetchone()[0]
    print(n)
except:
    print(0)
" 2>/dev/null || echo "0")
  if [ "$CSBS_COUNT" = "0" ]; then
    echo ""
    echo "Found csbs-syllabus-2021.pdf — parsing CSBS courses (new codes only)..."
    "$PYTHON" "$ROOT/scripts/parse_pdf.py" --pdf csbs-syllabus-2021.pdf --skip-existing
  else
    echo "CSBS syllabus already loaded ($CSBS_COUNT courses)."
  fi
fi

COURSES=$(python3 -c "
import sqlite3
try:
    conn = sqlite3.connect('$DB')
    n = conn.execute('SELECT COUNT(*) FROM courses').fetchone()[0]
    print(n)
except:
    print('?')
" 2>/dev/null || echo "?")
echo "Database ready — $COURSES courses loaded."

# 3b) Build vector index (only if it doesn't exist yet)
CHROMA_DIR="$ROOT/data/chroma"
if [ ! -d "$CHROMA_DIR" ]; then
  echo ""
  echo "Building vector index for AI search..."
  "$PYTHON" "$ROOT/scripts/build_vectors.py"
else
  echo "Vector index ready."
fi

# 4) Check for Groq API key
if [ -z "$GROQ_API_KEY" ]; then
  echo ""
  echo "WARNING: GROQ_API_KEY is not set. AI chat will not work."
  echo "Get a free key at: https://console.groq.com/keys"
  echo "Then run: export GROQ_API_KEY=your_key_here"
  echo ""
fi

# 5) Start backend
echo ""
echo "Starting server at http://localhost:8000"
echo "Open your browser to: http://localhost:8000"
echo "Press Ctrl+C to stop."
echo ""
cd "$ROOT/backend" && "$VENV/bin/uvicorn" main:app --host 0.0.0.0 --port 8000 --reload
