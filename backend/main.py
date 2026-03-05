#!/usr/bin/env python3
"""
main.py — FastAPI backend for SRM Syllabus Finder.

Endpoints:
  GET  /api/search?q=<query>       search by code or name
  GET  /api/course/<code>          fetch one course by exact code
  GET  /api/suggest?q=<partial>    autocomplete suggestions
  GET  /api/stats                  database statistics
  POST /api/chat                   AI-powered Q&A (RAG with Gemini)

Static frontend is served from ../frontend/
"""

import json
import os
import re
import sqlite3
from pathlib import Path

import chromadb
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).parent.parent
DB_PATH      = ROOT / "data" / "syllabi.db"
CHROMA_DIR   = ROOT / "data" / "chroma"
FRONTEND_DIR = ROOT / "frontend"

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="SRM Syllabus Finder", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

RE_CODE = re.compile(r'\b(21[A-Z]{2,5}\d{3}[A-Z]?)\b', re.IGNORECASE)

# ── Gemini setup ──────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
gemini_model = None

def get_gemini_model():
    global gemini_model
    if gemini_model is None:
        if not GEMINI_API_KEY:
            raise HTTPException(
                status_code=503,
                detail="GEMINI_API_KEY not set. Add it as an environment variable.",
            )
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel("gemini-2.0-flash")
    return gemini_model


# ── ChromaDB setup ────────────────────────────────────────────────────────────
chroma_collection = None

def get_chroma():
    global chroma_collection
    if chroma_collection is None:
        if not CHROMA_DIR.exists():
            raise HTTPException(
                status_code=503,
                detail="Vector index not found. Run: python scripts/build_vectors.py",
            )
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        chroma_collection = client.get_collection("syllabus")
    return chroma_collection


# ── DB helper ─────────────────────────────────────────────────────────────────
def get_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="Database not found. Run: python scripts/parse_pdf.py"
        )
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row) -> dict:
    d = dict(row)
    for key in ("clrs", "cos", "units", "resources"):
        try:
            d[key] = json.loads(d.get(key) or "[]")
        except (json.JSONDecodeError, TypeError):
            d[key] = []
    d.pop("raw_text", None)   # don't send raw text to client
    return d


# ── Response formatter ────────────────────────────────────────────────────────
def format_markdown(row) -> str:
    d = row_to_dict(row)
    code, name = d["code"], d["name"]
    cat  = d.get("category", "")
    l, t, p, c = d["l"], d["t"], d["p"], d["c"]
    dept   = d.get("department", "")
    prereq = d.get("prereq", "Nil")
    coreq  = d.get("coreq", "Nil")
    clrs   = d.get("clrs", [])
    cos    = d.get("cos", [])
    units  = d.get("units", [])
    res    = d.get("resources", [])

    lines = [f"## {code} — {name}"]
    meta  = []
    if cat:
        meta.append(f"**Category:** {cat}")
    meta.append(f"**L-T-P-C:** {l}-{t}-{p}-{c} &nbsp;(Credits: {c})")
    if dept:
        meta.append(f"**Department:** {dept}")
    if prereq and prereq.lower() not in ("nil", "none", ""):
        meta.append(f"**Pre-requisite:** {prereq}")
    if coreq and coreq.lower() not in ("nil", "none", ""):
        meta.append(f"**Co-requisite:** {coreq}")
    lines.append("  \n".join(meta))
    lines.append("")

    if clrs:
        lines.append("### Course Learning Rationale (CLR)")
        for item in clrs:
            lines.append(f"- {item}")
        lines.append("")

    if cos:
        lines.append("### Course Outcomes (CO)")
        for item in cos:
            lines.append(f"- {item}")
        lines.append("")

    if units:
        lines.append("### Syllabus")
        for u in units:
            lines.append(f"\n**Unit {u['number']}: {u['title']}** &nbsp;({u['hours']} hrs)")
            lines.append(u["content"])
        lines.append("")

    if res:
        lines.append("### Learning Resources")
        for i, r in enumerate(res, 1):
            lines.append(f"{i}. {r}")

    return "\n".join(lines)


# ── Endpoints ──────────────────────────────────────────────────────────────────
@app.get("/api/search")
def search(q: str = Query(..., min_length=1)):
    conn = get_conn()
    try:
        q_up = q.strip().upper()

        # 1) Exact course-code match
        code_m = RE_CODE.search(q_up)
        if code_m:
            row = conn.execute(
                "SELECT * FROM courses WHERE UPPER(code) = ?", (code_m.group(1),)
            ).fetchone()
            if row:
                return {
                    "type":     "course",
                    "course":   row_to_dict(row),
                    "response": format_markdown(row),
                }

        # 2) Name contains all words in the query
        words  = q_up.split()
        clause = " AND ".join(["UPPER(name) LIKE ?"] * len(words))
        params = [f"%{w}%" for w in words]
        rows   = conn.execute(
            f"SELECT * FROM courses WHERE {clause} LIMIT 8", params
        ).fetchall()

        if rows:
            if len(rows) == 1:
                return {
                    "type":     "course",
                    "course":   row_to_dict(rows[0]),
                    "response": format_markdown(rows[0]),
                }
            matches = [{"code": r["code"], "name": r["name"], "category": r["category"], "c": r["c"]} for r in rows]
            body = "Multiple courses match your query:\n\n"
            for m in matches:
                body += f"- **{m['code']}** — {m['name']} ({m['category']}, {m['c']} credits)\n"
            body += "\nType a course code for full details."
            return {"type": "list", "matches": matches, "response": body}

        # 3) Partial code match
        rows = conn.execute(
            "SELECT * FROM courses WHERE UPPER(code) LIKE ? LIMIT 8", (f"%{q_up}%",)
        ).fetchall()
        if rows:
            if len(rows) == 1:
                return {
                    "type":     "course",
                    "course":   row_to_dict(rows[0]),
                    "response": format_markdown(rows[0]),
                }
            matches = [{"code": r["code"], "name": r["name"], "category": r["category"], "c": r["c"]} for r in rows]
            body = f"Found {len(matches)} courses with code matching **{q}**:\n\n"
            for m in matches:
                body += f"- **{m['code']}** — {m['name']}\n"
            return {"type": "list", "matches": matches, "response": body}

        return {
            "type":     "not_found",
            "response": (
                f"No course found for **{q}**.\n\n"
                "Try:\n"
                "- A course code like `21CSC201J`\n"
                "- Keywords from the course name like `data structures`"
            ),
        }
    finally:
        conn.close()


@app.get("/api/course/{code}")
def get_course(code: str):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM courses WHERE UPPER(code) = ?", (code.upper(),)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"Course {code} not found")
        return {
            "type":     "course",
            "course":   row_to_dict(row),
            "response": format_markdown(row),
        }
    finally:
        conn.close()


@app.get("/api/suggest")
def suggest(q: str = Query(..., min_length=2)):
    conn = get_conn()
    try:
        q_up = q.upper()
        rows = conn.execute(
            """SELECT code, name, category FROM courses
               WHERE UPPER(code) LIKE ? OR UPPER(name) LIKE ?
               ORDER BY
                 CASE WHEN UPPER(code) LIKE ? THEN 0 ELSE 1 END,
                 code
               LIMIT 10""",
            (f"{q_up}%", f"%{q_up}%", f"{q_up}%"),
        ).fetchall()
        return {"suggestions": [{"code": r["code"], "name": r["name"], "category": r["category"]} for r in rows]}
    finally:
        conn.close()


@app.get("/api/stats")
def stats():
    conn = get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
        cats  = conn.execute(
            "SELECT category, COUNT(*) AS n FROM courses GROUP BY category ORDER BY n DESC"
        ).fetchall()
        depts = conn.execute(
            "SELECT department, COUNT(*) AS n FROM courses GROUP BY department ORDER BY n DESC LIMIT 10"
        ).fetchall()
        return {
            "total_courses":  total,
            "by_category":    {r["category"]: r["n"] for r in cats},
            "by_department":  {r["department"]: r["n"] for r in depts},
        }
    finally:
        conn.close()


# ── AI Chat endpoint (RAG) ────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are the SRM Syllabus Assistant, an AI helper for students at SRM Institute of Science and Technology (School of Computing, Regulations 2021).

Your job:
- Answer questions about courses, syllabi, prerequisites, credits, units, textbooks, and course outcomes using ONLY the provided syllabus context.
- Be helpful, clear, and concise. Use markdown formatting for readability.
- If the context doesn't contain enough information to answer, say so honestly — don't make things up.
- When referencing courses, always mention the course code and name.
- You can compare courses, suggest prerequisites, explain what a unit covers, list textbooks, etc.
- Keep responses focused and student-friendly.

IMPORTANT: Only use information from the provided context. Do not invent course details."""


@app.post("/api/chat")
async def chat_endpoint(request: Request):
    body = await request.json()
    question = body.get("question", "").strip()
    if not question:
        raise HTTPException(400, "No question provided")

    # 1) Retrieve relevant chunks from ChromaDB
    collection = get_chroma()
    results = collection.query(
        query_texts=[question],
        n_results=8,
    )

    context_chunks = results["documents"][0] if results["documents"] else []

    if not context_chunks:
        return {"response": "I couldn't find any relevant syllabus information for your question. Try asking about a specific course code or topic."}

    # 2) Build prompt with context
    context_text = "\n\n---\n\n".join(context_chunks)
    user_prompt = f"""Based on the following syllabus information, answer the student's question.

=== SYLLABUS CONTEXT ===
{context_text}
=== END CONTEXT ===

Student's question: {question}"""

    # 3) Call Gemini
    model = get_gemini_model()

    async def generate_stream():
        try:
            response = model.generate_content(
                [
                    {"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\n" + user_prompt}]},
                ],
                stream=True,
            )
            for chunk in response:
                if chunk.text:
                    yield f"data: {json.dumps({'text': chunk.text})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate_stream(), media_type="text/event-stream")


# ── Serve frontend ─────────────────────────────────────────────────────────────
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")


# ── Dev entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
