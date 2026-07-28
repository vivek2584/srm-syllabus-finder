#!/usr/bin/env python3
"""
parse_pdf_2026.py — Extract courses from the 2026 SRM syllabus PDF using Groq LLM.
"""

import sys
import os
import re
import json
import sqlite3
import argparse
import time
from pathlib import Path
import pdfplumber
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "syllabi.db"
DEFAULT_PDF = "first-year-syllabus-all-programmes-2026.pdf"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    print("WARNING: GROQ_API_KEY not set. Cannot run LLM parsing.")
    sys.exit(1)

client = Groq(api_key=GROQ_API_KEY)

def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def extract_courses(pdf_path: Path):
    pages = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            pages.append(text or "")

    # Group pages into courses
    courses_text = []
    current_course = []
    starts = []
    
    for i, text in enumerate(pages):
        # Detect start of course
        if re.search(r'Code\s+(26[A-Z0-9]+)\s+Title', text, re.IGNORECASE):
            if current_course:
                courses_text.append((starts[-1], i-1, "\n".join(current_course)))
            current_course = [text]
            starts.append(i)
        elif current_course:
            current_course.append(text)
            
    if current_course:
        courses_text.append((starts[-1], len(pages)-1, "\n".join(current_course)))
        
    return courses_text

def parse_with_llm(text: str) -> dict:
    prompt = """
You are an expert data extractor. Extract the course syllabus from the provided text into the exact JSON format.
The text contains a table that has been flattened. Use your reasoning to accurately group topics under the 5 units.
Output ONLY valid JSON, starting with { and ending with }, with NO markdown formatting, NO backticks.

Expected JSON format:
{
  "code": "26...",
  "name": "Course Title",
  "category": "Course Category",
  "l": 2, "t": 0, "p": 2, "c": 3,
  "department": "Offering Department",
  "prereq": "Nil",
  "coreq": "Nil",
  "clrs": ["CLR-1: text...", "CLR-2: text..."],
  "cos": ["CO-1: text...", "CO-2: text..."],
  "units": [
     {"number": 1, "title": "Unit 1 Title", "hours": 12, "content": "Topics covered..."},
     {"number": 2, "title": "Unit 2 Title", "hours": 12, "content": "Topics covered..."}
  ],
  "resources": ["1. Book A...", "2. Book B..."]
}

Text to parse:
""" + text[:6000]

    for attempt in range(3):
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model="llama-3.3-70b-versatile",
                temperature=0.1,
            )
            out = chat_completion.choices[0].message.content.strip()
            if out.startswith("```json"):
                out = out[7:]
            if out.startswith("```"):
                out = out[3:]
            if out.endswith("```"):
                out = out[:-3]
            
            return json.loads(out.strip())
        except Exception as e:
            print(f"Attempt {attempt+1} failed: {e}")
            time.sleep(2)
            
    return None

def main():
    pdf_path = ROOT / DEFAULT_PDF
    if not pdf_path.exists():
        sys.exit(f"PDF not found at {pdf_path}")
        
    print("Extracting text from PDF...")
    course_blocks = extract_courses(pdf_path)
    print(f"Found {len(course_blocks)} courses.")
    
    conn = init_db(DB_PATH)
    
    for start_page, end_page, text in course_blocks:
        code_match = re.search(r'Code\s+(26[A-Z0-9]+)\s+Title', text, re.IGNORECASE)
        code = code_match.group(1) if code_match else "UNKNOWN"
        
        # Check if already parsed
        existing = conn.execute("SELECT id FROM courses WHERE UPPER(code)=? AND regulation='2026'", (code.upper(),)).fetchone()
        if existing:
            print(f"Skipping {code} (already in DB)")
            continue
            
        print(f"Parsing {code} with LLM...")
        data = parse_with_llm(text)
        if not data:
            print(f"Failed to parse {code}")
            continue
            
        # Ensure ints
        try:
            l = int(data.get("l", 0))
            t = int(data.get("t", 0))
            p = int(data.get("p", 0))
            c = int(data.get("c", 0))
        except:
            l, t, p, c = 0, 0, 0, 0
            
        try:
            conn.execute(
                """INSERT OR REPLACE INTO courses
                   (code, name, category, l, t, p, c, department, prereq, coreq,
                    clrs, cos, units, resources, raw_text, start_page, end_page,
                    source_pdf, regulation)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.get("code", code), data.get("name", ""), data.get("category", ""),
                    l, t, p, c,
                    data.get("department", ""), data.get("prereq", "Nil"), data.get("coreq", "Nil"),
                    json.dumps(data.get("clrs", [])),  json.dumps(data.get("cos", [])),
                    json.dumps(data.get("units", [])), json.dumps(data.get("resources", [])),
                    text, start_page, end_page,
                    pdf_path.name, '2026'
                )
            )
            conn.commit()
            print(f"Saved {code} to database.")
        except Exception as e:
            print(f"DB Error for {code}: {e}")
            
        time.sleep(3) # Rate limit

if __name__ == "__main__":
    main()
