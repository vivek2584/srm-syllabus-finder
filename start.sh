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
else
  COURSES=$(sqlite3 "$DB" "SELECT COUNT(*) FROM courses;" 2>/dev/null || echo "?")
  echo "Database ready — $COURSES courses loaded."
fi

# 4) Start backend
echo ""
echo "Starting server at http://localhost:8000"
echo "Open your browser to: http://localhost:8000"
echo "Press Ctrl+C to stop."
echo ""
cd "$ROOT/backend" && "$VENV/bin/uvicorn" main:app --host 0.0.0.0 --port 8000 --reload
