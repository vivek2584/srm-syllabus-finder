#!/usr/bin/env bash
# start.sh — one-command launcher for SRM Syllabus Finder
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv"
DB="$ROOT/data/syllabi.db"
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"
SYLLABI_DIR="$ROOT/syllabi"

echo "=== SRM Syllabus Finder ==="

# 1) Create virtual environment if needed
if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV"
fi

# 2) Install dependencies
echo "Checking dependencies..."
"$PIP" install -q -r "$ROOT/requirements.txt"

# 3) Parse main computing PDF → DB (only if DB doesn't exist yet)
COMPUTING_PDF="$SYLLABI_DIR/computing-programmes-syllabus-2021.pdf"
if [ ! -f "$DB" ]; then
  echo ""
  if [ -f "$COMPUTING_PDF" ]; then
    echo "Database not found. Parsing computing programmes PDF — this takes a few minutes..."
    "$PYTHON" "$ROOT/scripts/parse_pdf.py" --pdf computing-programmes-syllabus-2021.pdf
  else
    echo "WARNING: computing-programmes-syllabus-2021.pdf not found in syllabi/."
    echo "Place it there and re-run to populate the database."
  fi
fi

# 4) Parse any PDFs in syllabi/ that haven't been loaded yet (skip-existing mode)
if [ -d "$SYLLABI_DIR" ]; then
  for PDF_PATH in "$SYLLABI_DIR"/*.pdf; do
    [ -f "$PDF_PATH" ] || continue
    PDF_NAME="$(basename "$PDF_PATH")"

    # Skip the main computing PDF — already handled above (first-time init)
    [ "$PDF_NAME" = "computing-programmes-syllabus-2021.pdf" ] && continue

    LOADED=$(python3 -c "
import sqlite3
try:
    conn = sqlite3.connect('$DB')
    n = conn.execute(\"SELECT COUNT(*) FROM courses WHERE source_pdf=?\", ('$PDF_NAME',)).fetchone()[0]
    print(n)
except:
    print(0)
" 2>/dev/null || echo "0")

    if [ "$LOADED" = "0" ]; then
      echo ""
      echo "Found $PDF_NAME — parsing new courses (skip-existing mode)..."
      "$PYTHON" "$ROOT/scripts/parse_pdf.py" --pdf "$PDF_NAME" --skip-existing
    else
      echo "  $PDF_NAME already loaded ($LOADED courses)."
    fi
  done
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
echo ""
echo "Database ready — $COURSES courses loaded."

# 5) Build vector index (only if it doesn't exist yet)
CHROMA_DIR="$ROOT/data/chroma"
if [ ! -d "$CHROMA_DIR" ]; then
  echo ""
  echo "Building vector index for AI search..."
  "$PYTHON" "$ROOT/scripts/build_vectors.py"
else
  echo "Vector index ready."
fi

# 6) Check for Groq API key
if [ -z "$GROQ_API_KEY" ]; then
  echo ""
  echo "WARNING: GROQ_API_KEY is not set. AI chat will not work."
  echo "Get a free key at: https://console.groq.com/keys"
  echo "Then run: export GROQ_API_KEY=your_key_here"
  echo ""
fi

# 7) Start backend
echo ""
echo "Starting server at http://localhost:8000"
echo "Open your browser to: http://localhost:8000"
echo "Press Ctrl+C to stop."
echo ""
cd "$ROOT/backend" && "$VENV/bin/uvicorn" main:app --host 0.0.0.0 --port 8000 --reload
