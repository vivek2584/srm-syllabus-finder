#!/usr/bin/env python3
"""
main.py — FastAPI backend for SRM Syllabus Finder.

Endpoints:
  GET  /api/search?q=<query>       search by code or name
  GET  /api/course/<code>          fetch one course by exact code
  GET  /api/suggest?q=<partial>    autocomplete suggestions
  GET  /api/stats                  database statistics
  POST /api/chat                   AI-powered Q&A (RAG with Groq)

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
from fastapi.responses import StreamingResponse
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

# ── Groq setup ───────────────────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
groq_client = None

GROQ_MODEL = "llama-3.3-70b-versatile"

def get_groq_client():
    global groq_client
    if groq_client is None:
        if not GROQ_API_KEY:
            raise HTTPException(
                status_code=503,
                detail="GROQ_API_KEY not set. Add it as an environment variable.",
            )
        from groq import Groq
        groq_client = Groq(api_key=GROQ_API_KEY)
    return groq_client


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

FIRST STEP — before generating any answer:
Check whether the provided context contains information relevant to the student's question. If it does not, refuse immediately — do NOT attempt to answer from your own knowledge.

Your job:
- Answer questions about courses, syllabi, prerequisites, credits, units, textbooks, and course outcomes using ONLY the provided syllabus context.
- Be helpful, clear, and concise. Use markdown formatting for readability.
- Always bold course codes (e.g., **21CSC201J**) and mention the course name alongside.
- Keep responses focused and student-friendly.

Context format: Each course chunk is one of these types:
- **Overview**: course code, name, category, credits (L-T-P-C), department, prerequisites, co-requisites, CLRs, COs.
- **Unit**: unit number, title, hours, and detailed topic list.
- **Resources**: textbooks and reference materials.

Formatting templates:
- Single course detail → Use a heading (## Code — Name), then bulleted/numbered sections for units, COs, resources, etc.
- Multiple courses or comparison → Use a markdown table (| Feature | Course A | Course B |).
- Lists (units, textbooks, COs) → Always use numbered or bulleted lists, never inline paragraphs.

Response guidelines:
- When asked about prerequisites, also mention the credit structure.
- For "what does unit X cover" questions, list the topics clearly.
- If you see data for multiple courses, address all of them — don't ignore any.
- ALWAYS include ALL units present in the context — never skip or summarize units. If the context has 5 units, list all 5.
- If your response is getting long, prioritize units and topic details over CLRs and COs. Never cut off mid-section — finish the current section or omit it entirely.

STRICT RULES — violating these is unacceptable:
- ONLY use information explicitly present in the provided context. Do not use your training knowledge to fill gaps.
- If the context does not contain the answer, respond ONLY with: "I don't have that information in the syllabus database. Try asking about a specific course code or topic."
- NEVER invent, guess, or assume course codes, course names, unit contents, textbooks, credit values, or any other details.
- If the question is unrelated to SRM syllabi/courses, say: "I can only help with questions about SRM course syllabi."
- Do NOT answer general knowledge questions even if the topic appears in a course (e.g., if asked "explain binary trees", only answer with what the syllabus says, not a general CS explanation)."""


# ── Chat helpers ──────────────────────────────────────────────────────────────
STOP_WORDS = {"WHAT", "WHICH", "WHERE", "WHEN", "HOW", "WHO", "ARE", "THE",
              "FOR", "AND", "WITH", "ABOUT", "DOES", "THIS", "THAT", "FROM",
              "HAVE", "HAS", "CAN", "WILL", "TELL", "ME", "IN", "OF", "TO",
              "IS", "IT", "DO", "A", "AN", "ON", "AT", "BY", "OR", "BE",
              "ALL", "ANY", "NOT", "NO", "SO", "IF", "BUT", "MY", "ITS",
              "COURSE", "COURSES", "SYLLABUS", "SUBJECT", "UNITS", "UNIT",
              "PREREQUISITES", "PREREQUISITE", "TEXTBOOKS", "TEXTBOOK",
              "EXPLAIN", "DESCRIBE", "LIST", "COMPARE", "COVER", "COVERS",
              "TOPICS", "TOPIC", "DETAILS", "DETAIL", "BETWEEN", "VS",
              "DIFFERENCE", "DIFFERENCES", "VERSUS", "WHAT'S", "WHATS",
              "FULL", "COMPLETE", "ENTIRE", "WHOLE", "BRIEF", "SHORT",
              "SUMMARY", "OVERVIEW", "DETAILED", "INFO", "INFORMATION",
              "GIVE", "SHOW", "PLEASE", "NEED", "WANT", "KNOW", "GET",
              "SRM", "SRMIST", "UNIVERSITY"}

RE_CREDIT = re.compile(r'(\d+)\s*(?:credit|credits)\b', re.IGNORECASE)
RE_CATEGORY = re.compile(
    r'\b(core|elective|professional|open|mandatory|audit|lab)\b', re.IGNORECASE
)


def resolve_courses(question: str, conn) -> list[str]:
    """Resolve a question to course codes using SQL name search."""
    q_up = question.upper()

    # Filter stop words
    words = [w for w in q_up.split() if w not in STOP_WORDS and len(w) > 1]
    if not words:
        return []

    clause = " AND ".join(["UPPER(name) LIKE ?"] * len(words))
    params = [f"%{w}%" for w in words]
    rows = conn.execute(
        f"SELECT code FROM courses WHERE {clause} LIMIT 3", params
    ).fetchall()
    return [r["code"] for r in rows]


def detect_aggregate_query(question: str) -> dict | None:
    """Detect if the question is an aggregate/listing query that should use SQL."""
    q_up = question.upper()

    # Credit-based queries: "which courses have 4 credits"
    credit_match = RE_CREDIT.search(question)
    cat_match = RE_CATEGORY.search(question)

    if credit_match and any(kw in q_up for kw in ("WHICH", "LIST", "WHAT", "ALL", "SHOW")):
        return {"type": "credits", "value": int(credit_match.group(1))}

    if cat_match and any(kw in q_up for kw in ("WHICH", "LIST", "WHAT", "ALL", "SHOW")):
        return {"type": "category", "value": cat_match.group(1).upper()}

    if any(phrase in q_up for phrase in ("HOW MANY COURSES", "TOTAL COURSES", "COUNT OF COURSES")):
        return {"type": "count"}

    return None


def handle_aggregate_query(query_info: dict, conn) -> str:
    """Handle aggregate queries with direct SQL and return a markdown response."""
    qtype = query_info["type"]

    if qtype == "credits":
        credits = query_info["value"]
        rows = conn.execute(
            "SELECT code, name, category FROM courses WHERE c = ? ORDER BY code",
            (credits,)
        ).fetchall()
        if not rows:
            return f"No courses found with **{credits} credits**."
        lines = [f"## Courses with {credits} Credits ({len(rows)} found)\n"]
        for r in rows:
            lines.append(f"- **{r['code']}** — {r['name']} ({r['category']})")
        return "\n".join(lines)

    if qtype == "category":
        cat = query_info["value"]
        rows = conn.execute(
            "SELECT code, name, c FROM courses WHERE UPPER(category) LIKE ? ORDER BY code",
            (f"%{cat}%",)
        ).fetchall()
        if not rows:
            return f"No **{cat.lower()}** courses found."
        lines = [f"## {cat.title()} Courses ({len(rows)} found)\n"]
        for r in rows:
            lines.append(f"- **{r['code']}** — {r['name']} ({r['c']} credits)")
        return "\n".join(lines)

    if qtype == "count":
        total = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
        cats = conn.execute(
            "SELECT category, COUNT(*) AS n FROM courses GROUP BY category ORDER BY n DESC"
        ).fetchall()
        lines = [f"## Course Statistics\n", f"**Total courses:** {total}\n"]
        for c in cats:
            lines.append(f"- {c['category']}: {c['n']}")
        return "\n".join(lines)

    return ""


@app.post("/api/chat")
async def chat_endpoint(request: Request):
    body = await request.json()
    question = body.get("question", "").strip()
    if not question:
        raise HTTPException(400, "No question provided")

    # 0) Check if this is an aggregate query (credit/category/count listing)
    agg = detect_aggregate_query(question)
    if agg:
        conn = get_conn()
        try:
            response = handle_aggregate_query(agg, conn)
        finally:
            conn.close()
        if response:
            agg_title = response.split('\n')[0].replace('## ', '').strip()
            async def send_aggregate():
                yield f"data: {json.dumps({'meta': {'title': agg_title}})}\n\n"
                yield f"data: {json.dumps({'text': response})}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(send_aggregate(), media_type="text/event-stream")

    # 1) Retrieve relevant chunks from ChromaDB
    collection = get_chroma()

    # If question mentions course codes, use metadata filtering
    mentioned_codes = [m.group(1).upper() for m in RE_CODE.finditer(question)]

    # If no course codes found, try to resolve via course name search
    if not mentioned_codes:
        conn = get_conn()
        try:
            mentioned_codes = resolve_courses(question, conn)
        finally:
            conn.close()

    if mentioned_codes:
        # Fetch chunks for each mentioned course via metadata filter
        # Each course has ~7 chunks (overview + 5 units + resources), scale accordingly
        n = max(12, len(mentioned_codes) * 8)
        if len(mentioned_codes) == 1:
            where_filter = {"code": mentioned_codes[0]}
        else:
            where_filter = {"code": {"$in": mentioned_codes}}

        results = collection.query(
            query_texts=[question],
            n_results=n,
            where=where_filter,
        )
    else:
        # Pure semantic search for general questions
        results = collection.query(
            query_texts=[question],
            n_results=8,
        )

    context_chunks = results["documents"][0] if results["documents"] else []

    if not context_chunks:
        return {"response": "I couldn't find any relevant syllabus information for your question. Try asking about a specific course code or topic."}

    # Look up course names for metadata
    course_names = []
    if mentioned_codes:
        conn = get_conn()
        try:
            for code in mentioned_codes:
                row = conn.execute(
                    "SELECT name FROM courses WHERE UPPER(code) = ?", (code,)
                ).fetchone()
                if row:
                    course_names.append({"code": code, "name": row["name"]})
        finally:
            conn.close()

    # 2) Build prompt with context
    context_text = "\n\n---\n\n".join(context_chunks)
    user_prompt = f"""Based on the following syllabus information, answer the student's question.

=== SYLLABUS CONTEXT ===
{context_text}
=== END CONTEXT ===

Student's question: {question}

Remember: ONLY use information from the context above. If the answer is not in the context, say you don't have that information."""

    # 3) Call Groq (Llama 3.3 70B)
    async def generate_stream():
        try:
            # Send metadata first so frontend knows course context
            if course_names:
                yield f"data: {json.dumps({'meta': {'courses': course_names}})}\n\n"

            client = get_groq_client()
            stream = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                stream=True,
                temperature=0.2,
                max_tokens=1500,
            )
            for chunk in stream:
                text = chunk.choices[0].delta.content
                if text:
                    yield f"data: {json.dumps({'text': text})}\n\n"
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
