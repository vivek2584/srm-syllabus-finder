#!/usr/bin/env python3
"""
build_vectors.py — Build ChromaDB vector index from the SQLite syllabus database.

Reads every course from syllabi.db, chunks the content, and stores embeddings
in a persistent ChromaDB collection.  Uses ChromaDB's built-in sentence-transformer
embeddings (no API key needed for this step).

Usage:
    python scripts/build_vectors.py          # build from default paths
"""

import json
import sqlite3
import sys
from pathlib import Path

import chromadb

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syllabi.db"
CHROMA_DIR = ROOT / "data" / "chroma"
COLLECTION = "syllabus"


def load_courses(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM courses").fetchall()
    conn.close()
    courses = []
    for r in rows:
        d = dict(r)
        for key in ("clrs", "cos", "units", "resources"):
            try:
                d[key] = json.loads(d.get(key) or "[]")
            except (json.JSONDecodeError, TypeError):
                d[key] = []
        courses.append(d)
    return courses


def chunk_course(course: dict) -> list[tuple[str, dict]]:
    """Split a course into meaningful text chunks with metadata."""
    code = course["code"]
    name = course["name"]
    meta = {
        "code": code,
        "name": name,
        "category": course.get("category", ""),
        "credits": course.get("c", 0),
    }

    chunks = []

    # Overview chunk
    overview_parts = [f"Course: {code} — {name}"]
    if course.get("category"):
        overview_parts.append(f"Category: {course['category']}")
    overview_parts.append(f"Credits (L-T-P-C): {course['l']}-{course['t']}-{course['p']}-{course['c']}")
    if course.get("department"):
        overview_parts.append(f"Department: {course['department']}")
    if course.get("prereq") and course["prereq"].lower() not in ("nil", "none", ""):
        overview_parts.append(f"Pre-requisite: {course['prereq']}")
    if course.get("coreq") and course["coreq"].lower() not in ("nil", "none", ""):
        overview_parts.append(f"Co-requisite: {course['coreq']}")
    if course.get("clrs"):
        overview_parts.append("Course Learning Rationale:")
        for clr in course["clrs"]:
            overview_parts.append(f"  - {clr}")
    if course.get("cos"):
        overview_parts.append("Course Outcomes:")
        for co in course["cos"]:
            overview_parts.append(f"  - {co}")
    chunks.append(("\n".join(overview_parts), {**meta, "chunk_type": "overview"}))

    # Unit chunks
    for u in course.get("units", []):
        unit_text = f"Course: {code} — {name}\nUnit {u['number']}: {u['title']} ({u['hours']} hours)\n{u['content']}"
        chunks.append((unit_text, {**meta, "chunk_type": "unit", "unit_number": u["number"]}))

    # Resources chunk
    if course.get("resources"):
        res_text = f"Course: {code} — {name}\nLearning Resources:\n"
        for i, r in enumerate(course["resources"], 1):
            res_text += f"  {i}. {r}\n"
        chunks.append((res_text, {**meta, "chunk_type": "resources"}))

    return chunks


def main():
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        print("Run: python scripts/parse_pdf.py")
        sys.exit(1)

    print(f"Loading courses from {DB_PATH}...")
    courses = load_courses(DB_PATH)
    print(f"  Found {len(courses)} courses")

    # Prepare all chunks
    all_docs = []
    all_metas = []
    all_ids = []

    for course in courses:
        chunks = chunk_course(course)
        for i, (text, meta) in enumerate(chunks):
            doc_id = f"{course['code']}_{i}"
            all_docs.append(text)
            all_metas.append(meta)
            all_ids.append(doc_id)

    print(f"  Generated {len(all_docs)} chunks")

    # Build ChromaDB
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # Delete existing collection if it exists, then recreate
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    # Add in batches (ChromaDB has a batch size limit)
    BATCH = 500
    for start in range(0, len(all_docs), BATCH):
        end = min(start + BATCH, len(all_docs))
        collection.add(
            documents=all_docs[start:end],
            metadatas=all_metas[start:end],
            ids=all_ids[start:end],
        )
        print(f"  Indexed {end}/{len(all_docs)} chunks")

    print(f"Vector index saved to {CHROMA_DIR}")
    print("Done.")


if __name__ == "__main__":
    main()
