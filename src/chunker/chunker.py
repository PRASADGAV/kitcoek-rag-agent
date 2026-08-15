"""
Chunker module — KITCOEK RAG Agent

Loads every JSON file produced by the scraper, cleans the text,
splits it into smaller overlapping chunks (300 words / 50-word overlap),
and attaches rich metadata to each chunk.

Smaller chunks = more precise retrieval hits + stay inside Groq TPM limits.
"""

import glob
import json
import os
import re
from typing import Any

# ---------------------------------------------------------------------------
# Category keywords (used to auto-tag each chunk)
# ---------------------------------------------------------------------------
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "admissions":  ["admission", "eligibility", "dte", "cap", "cutoff", "merit",
                    "apply", "application", "undergraduate", "postgraduate",
                    "mtech", "btech", "phd", "first year", "fy", "lateral"],
    "fees":        ["fee", "fees", "tuition", "scholarship", "payment",
                    "charges", "hostel fee", "fee structure", "fee proposal",
                    "refund", "concession", "freeship"],
    "academics":   ["syllabus", "curriculum", "course", "semester", "credit",
                    "timetable", "academic calendar", "nep", "honors",
                    "structure", "program", "programme", "subject"],
    "exams":       ["exam", "examination", "result", "marks", "grade", "cgpa",
                    "sgpa", "backlog", "hall ticket", "revaluation",
                    "paper setting", "question paper", "exam cell"],
    "placements":  ["placement", "recruit", "campus", "company", "package",
                    "internship", "lpa", "offer letter", "tnp", "tnp cell",
                    "placed", "hiring", "drive", "ctc"],
    "departments": ["department", "cse", "it", "mechanical", "civil",
                    "electrical", "e&tc", "entc", "hod", "faculty",
                    "biotechnology", "environmental", "aiml", "csbs",
                    "basic science", "humanities"],
    "research":    ["research", "publication", "journal", "project", "phd",
                    "conference", "patent", "ipr", "r&d", "sponsored",
                    "serb", "aicte grant", "nabard"],
    "campus":      ["library", "hostel", "canteen", "sports", "nss", "ncc",
                    "club", "event", "cultural", "fest", "incubation",
                    "startup", "lab", "centre", "facility", "infrastructure"],
    "contact":     ["contact", "phone", "mobile", "email", "address",
                    "location", "map", "reach", "helpline", "enquiry"],
    "notices":     ["notice", "circular", "announcement", "news", "update",
                    "tender", "notification", "latest"],
    "naac_nba":    ["naac", "nba", "accreditation", "iqac", "ranking",
                    "nirf", "grade", "autonomous", "approval", "aicte"],
    "people":      ["director", "principal", "hod", "professor", "faculty",
                    "dean", "staff", "trustee", "board", "administration",
                    "vanarotti", "shinde"],
}


def _detect_category(text: str, title: str) -> str:
    combined = (title + " " + text).lower()
    scores: dict[str, int] = {
        cat: sum(combined.count(kw) for kw in kws)
        for cat, kws in CATEGORY_KEYWORDS.items()
    }
    best = max(scores, key=lambda c: scores[c])
    return best if scores[best] > 0 else "general"


def _strip_nav_menu(text: str) -> str:
    """
    KITCOEK pages embed the full navigation menu in every SSR page.
    Strip everything up to (but not including) the first real content marker.
    This prevents ~41 near-identical nav chunks from flooding search results.
    """
    NAV_END_MARKERS = [
        "DIRECTOR'S MESSAGE", "Director's Message", "DIRECTOR's MESSAGE",
        "Prof. (Dr.)", "Prof.(Dr.)",
        "Established in 1983", "Established in May 1983",
        "NAAC Records", "NAAC Cycle",
        "Training and Placement", "T&P Cell", "TNP Cell", "Placement Cell",
        "Department of Computer Science", "Department of Civil",
        "Department of Mechanical", "Department of Electrical",
        "Department of Electronics", "Department of Biotechnology",
        "Department of Basic Science",
        "Scholarship", "Alumni Association",
        "Student Clubs", "Exam Timetable",
        "The KITCoEk Alumni", "KITCoEk Alumni",
        "following details are to be given",
        # Homepage-specific content markers
        "Engineers Graduated", "Qualified Faculties",
        "PLACEMENT NEWS", "Placement News",
        "KITCOEK OVERVIEW", "KITCoEK OVERVIEW",
        "An institute established",
        "Esteemed Recruiters",
        "652", "19,000",
        # Curated pages start with their own content — never strip them
        # (these are already clean, no nav to strip)
    ]
    # If this is a curated/clean page (no "EXAM CELL" nav header), skip stripping
    if "EXAM CELL" not in text[:200] and text[:5] != "ABOUT" and text[:4] != "HOME":
        return text
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if any(m.lower() in line.lower() for m in NAV_END_MARKERS):
            return "\n".join(lines[i:]).strip()
    return text  # no marker found — return as-is


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\t+", " ", text)

    lines = text.splitlines()
    clean: list[str] = []
    seen: set[str] = set()

    for ln in lines:
        ln = ln.strip()
        if len(ln) < 10:          # drop very short lines
            continue
        key = ln.lower()
        if key in seen:           # drop exact duplicates
            continue
        seen.add(key)
        clean.append(ln)

    return "\n".join(clean).strip()


# ---------------------------------------------------------------------------
# Splitter — 300-word chunks, 50-word overlap
# ---------------------------------------------------------------------------

def _split_into_chunks(
    text: str,
    chunk_size: int = 300,
    overlap: int = 50,
) -> list[str]:
    """
    Split text into overlapping word-count chunks.

    Tries to break on paragraph boundaries first so chunks stay coherent.
    A 300-word chunk ≈ 400 tokens — safe for Groq's free-tier TPM limits
    even when sending 3–4 chunks as context.
    """
    # Split on paragraph breaks first
    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]

    chunks: list[str] = []
    current_words: list[str] = []

    for para in paragraphs:
        para_words = para.split()

        if len(current_words) + len(para_words) <= chunk_size:
            current_words.extend(para_words)
        else:
            # Flush current buffer
            if current_words:
                chunks.append(" ".join(current_words))

            # If the paragraph itself is larger than chunk_size, hard-split it
            if len(para_words) > chunk_size:
                for start in range(0, len(para_words), chunk_size - overlap):
                    piece = para_words[start: start + chunk_size]
                    if piece:
                        chunks.append(" ".join(piece))
                current_words = para_words[-(overlap):]
            else:
                # Start new buffer with overlap from previous chunk
                overlap_words = current_words[-overlap:] if overlap else []
                current_words = overlap_words + para_words

    if current_words:
        chunks.append(" ".join(current_words))

    return [c for c in chunks if len(c.split()) >= 20]   # drop micro-chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_documents(
    raw_dir: str = "data/raw",
    chunk_size: int = 300,
    overlap: int = 50,
) -> list[dict[str, Any]]:
    """
    Load all JSON files under *raw_dir*, clean + chunk each document,
    return a flat list of chunk dicts ready for embedding.
    """
    json_files = sorted(glob.glob(
        os.path.join(raw_dir, "**", "*.json"), recursive=True
    ))
    # Exclude the pdf_links manifest
    json_files = [f for f in json_files if "pdf_links" not in os.path.basename(f)]

    if not json_files:
        print(f"[chunker] No JSON files found in {raw_dir}")
        return []

    all_chunks: list[dict[str, Any]] = []
    skipped = 0
    seen_texts: set[str] = set()   # global dedup across all documents

    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                record = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[chunker] Skipping {file_path}: {exc}")
            skipped += 1
            continue

        raw_text = record.get("text", "").strip()
        if not raw_text:
            skipped += 1
            continue

        title    = record.get("title", "")
        url      = record.get("url", "")
        doc_type = record.get("doc_type", "webpage")

        # Strip nav-menu boilerplate for web pages (every KITCOEK page has it)
        if doc_type == "webpage":
            raw_text = _strip_nav_menu(raw_text)

        text     = _clean_text(raw_text)

        splits   = _split_into_chunks(text, chunk_size=chunk_size, overlap=overlap)
        stem     = os.path.splitext(os.path.basename(file_path))[0]

        for idx, chunk_text in enumerate(splits):
            # Global dedup — skip chunks identical to one already seen
            normalized = re.sub(r"\s+", " ", chunk_text.lower().strip())
            if normalized in seen_texts:
                continue
            seen_texts.add(normalized)

            category = _detect_category(chunk_text, title)
            all_chunks.append({
                "chunk_id":     f"{stem}_chunk_{idx:03d}",
                "text":         chunk_text,
                "source_url":   url,
                "title":        title,
                "doc_type":     doc_type,
                "category":     category,
                "chunk_index":  idx,
                "total_chunks": len(splits),
            })

    print(f"[chunker] {len(all_chunks)} chunks from "
          f"{len(json_files) - skipped} files "
          f"({skipped} skipped).")
    return all_chunks
