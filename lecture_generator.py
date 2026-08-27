#!/usr/bin/env python3
"""
lecture_generator.py

Universal Multi-Book Pedagogical Audio Lecture Generation Engine.
Transforms any textbook (.pdf / .md / .txt) into modular, unhurried, 
conversational audio masterclasses adhering to cognitive load theory,
distributed active recall, and GraphRAG knowledge graph retrieval.

Defaults:
- Voice: Nigerian English Neural Voice (en-NG-AbeoNeural / en-NG-EzinneNeural)
- Speed: 100-110 Words Per Minute (rate: -18%)
- Architecture: Uncompressed masterclass with modular study break checkpoints
"""

import os
import re
import wave
import json
import io
import time
import asyncio
import argparse
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from pydub import AudioSegment


# ============================================================================
# 1. BOOK CATALOG & METADATA
# ============================================================================

class BookMetadata:
    def __init__(self, book_path: Path, config_data: Optional[Dict] = None):
        self.book_path = book_path
        self.config_data = config_data or {}
        
        # Derive slug
        if self.config_data.get("short_slug"):
            self.slug = self.config_data["short_slug"]
        elif book_path.is_dir():
            self.slug = book_path.name
        else:
            self.slug = re.sub(r"[^a-zA-Z0-9_]+", "_", book_path.stem).strip("_").lower()

        # Derive title
        if self.config_data.get("title") or self.config_data.get("book_title"):
            self.title = self.config_data.get("title") or self.config_data.get("book_title")
        else:
            self.title = book_path.stem.replace("_", " ").title()

        self.exam_body = self.config_data.get("exam_body", "Professional & Academic Examination")
        self.target_audience = self.config_data.get("target_audience", "Students and Examination Candidates")
        self.default_voice = self.config_data.get("default_voice", "en-NG-AbeoNeural")
        self.default_rate = self.config_data.get("default_rate", "-18%")


def resolve_book(book_arg: Optional[str]) -> Tuple[Path, BookMetadata]:
    """Resolves a book argument into a file path and metadata, supporting .md, .pdf, .docx, .doc, .epub, .txt."""
    books_dir = Path("books")
    supported_exts = [".md", ".pdf", ".docx", ".doc", ".epub", ".txt"]
    
    # 1. Check if argument is a path to a file or directory
    if book_arg:
        target = Path(book_arg)
        if target.exists():
            if target.is_dir():
                cfg_file = target / "book_config.json"
                cfg = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
                # Look for standard named book files
                for candidate in ["book.md", "book.pdf", "book.docx", "book.doc", "book.epub", "book.txt"]:
                    if (target / candidate).exists():
                        return target / candidate, BookMetadata(target / candidate, cfg)
                # Look for any supported file in the dir (excluding research blueprints and cache files)
                for ext in supported_exts:
                    for candidate in target.glob(f"*{ext}"):
                        if candidate.name != "deeper-research-report.md" and not candidate.name.endswith(".extracted.md") and not candidate.name.endswith(".extracted.txt"):
                            return candidate, BookMetadata(candidate, cfg)
            else:
                cfg_file = target.parent / "book_config.json"
                cfg = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
                return target, BookMetadata(target, cfg)
        
        # Check inside books/ directory by slug
        if (books_dir / book_arg).exists():
            return resolve_book(str(books_dir / book_arg))

    # 2. Default fallback: search books/ directory
    if books_dir.exists():
        for b_dir in sorted(books_dir.iterdir()):
            if b_dir.is_dir() and b_dir.name != "sample_book":
                return resolve_book(str(b_dir))

    # 3. Fallback to any supported document in workspace
    for ext in supported_exts:
        for p in Path(".").glob(f"*{ext}"):
            if "deep-research" not in p.name.lower() and "transcript" not in p.name.lower() and not p.name.startswith("."):
                return p, BookMetadata(p)
            
    raise FileNotFoundError(f"Could not find book matching '{book_arg}'. Check your path or books/ directory.")


# ============================================================================
# 2. UNIVERSAL MULTI-FORMAT BOOK PARSER (.MD, .PDF, .DOCX, .DOC, .EPUB, .TXT)
# ============================================================================

class UniversalBookParser:
    """Extracts text and parses chapters from Markdown, PDF, DOCX, DOC, EPUB, and Text files."""

    @classmethod
    def extract_full_text(cls, file_path: Path) -> str:
        """
        Extracts complete text content from any supported format into structured Markdown.
        Supported: .md, .txt, .pdf, .docx, .doc, .epub
        Features:
        - .docx: Converted to semantic Markdown via mammoth (tables, headers, bold, lists).
        - .doc: Converted via headless LibreOffice -> mammoth.
        - .epub: Converted via ebooklib + html2text.
        - .pdf: Hybrid pymupdf4llm + Targeted Gemini Vision OCR.
        - Auto-caches structured Markdown to books/<slug>/book.md or <file>.extracted.md.
        """
        suffix = file_path.suffix.lower()
        
        # 1. Plain Text & Markdown
        if suffix in [".md", ".txt"]:
            return file_path.read_text(encoding="utf-8")
            
        # 2. Microsoft Word (.docx)
        elif suffix == ".docx":
            cache_md = file_path.with_suffix(".extracted.md")
            book_md = file_path.parent / "book.md"
            if book_md.exists():
                return book_md.read_text(encoding="utf-8")
            if cache_md.exists():
                return cache_md.read_text(encoding="utf-8")

            print(f"\n[Smart Ingestion] Converting Word document (.docx) to Markdown: {file_path.name}...")
            import mammoth
            with open(str(file_path), "rb") as docx_file:
                result = mammoth.convert_to_markdown(docx_file)
                md_text = result.value
            
            cache_md.write_text(md_text, encoding="utf-8")
            if not book_md.exists():
                book_md.write_text(md_text, encoding="utf-8")
            print(f"[Smart Ingestion] Successfully converted .docx to Markdown: {cache_md} ({len(md_text):,} chars)")
            return md_text

        # 3. Legacy Microsoft Word (.doc)
        elif suffix == ".doc":
            cache_md = file_path.with_suffix(".extracted.md")
            book_md = file_path.parent / "book.md"
            if book_md.exists():
                return book_md.read_text(encoding="utf-8")
            if cache_md.exists():
                return cache_md.read_text(encoding="utf-8")

            print(f"\n[Smart Ingestion] Converting legacy Word document (.doc) to Markdown: {file_path.name}...")
            import subprocess
            import tempfile
            import mammoth
            
            with tempfile.TemporaryDirectory() as tmp_dir:
                subprocess.run([
                    "libreoffice", "--headless", "--convert-to", "docx",
                    str(file_path), "--outdir", tmp_dir
                ], check=True, capture_output=True)
                
                tmp_docx = Path(tmp_dir) / file_path.with_suffix(".docx").name
                if tmp_docx.exists():
                    with open(str(tmp_docx), "rb") as docx_file:
                        result = mammoth.convert_to_markdown(docx_file)
                        md_text = result.value
                else:
                    raise RuntimeError(f"Failed to convert {file_path.name} to .docx via LibreOffice")

            cache_md.write_text(md_text, encoding="utf-8")
            if not book_md.exists():
                book_md.write_text(md_text, encoding="utf-8")
            print(f"[Smart Ingestion] Successfully converted .doc to Markdown: {cache_md} ({len(md_text):,} chars)")
            return md_text

        # 4. EPUB eBooks (.epub)
        elif suffix == ".epub":
            cache_md = file_path.with_suffix(".extracted.md")
            book_md = file_path.parent / "book.md"
            if book_md.exists():
                return book_md.read_text(encoding="utf-8")
            if cache_md.exists():
                return cache_md.read_text(encoding="utf-8")

            print(f"\n[Smart Ingestion] Converting EPUB eBook to Markdown: {file_path.name}...")
            import ebooklib
            from ebooklib import epub
            import html2text

            book = epub.read_epub(str(file_path))
            converter = html2text.HTML2Text()
            converter.ignore_links = False
            converter.body_width = 0
            converter.ignore_images = False

            chapters_md = []
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    html_content = item.get_content().decode("utf-8", errors="ignore")
                    md_chunk = converter.handle(html_content).strip()
                    if md_chunk and len(md_chunk) > 50:
                        chapters_md.append(md_chunk)

            full_md = "\n\n---\n\n".join(chapters_md)
            cache_md.write_text(full_md, encoding="utf-8")
            if not book_md.exists():
                book_md.write_text(full_md, encoding="utf-8")
            print(f"[Smart Ingestion] Successfully converted .epub to Markdown: {cache_md} ({len(full_md):,} chars)")
            return full_md

        # 5. PDF Books (.pdf) via Hybrid pymupdf4llm + Checkpointed Vision OCR
        elif suffix == ".pdf":
            book_md = file_path.parent / "book.md"
            cache_md = file_path.with_suffix(".extracted.md")
            ocr_cache_dir = file_path.parent / ".ocr_cache"
            ocr_cache_dir.mkdir(parents=True, exist_ok=True)

            # Check if full verified completion cache exists
            if cache_md.exists():
                return cache_md.read_text(encoding="utf-8")

            print(f"\n[Smart Ingestion] Ingesting PDF via pymupdf4llm & Checkpointed Vision OCR: {file_path.name}...")
            import fitz  # PyMuPDF
            import pymupdf4llm
            from google.genai import types

            doc = fitz.open(str(file_path))
            total_pages = len(doc)
            print(f"[Smart Ingestion] Scanning {total_pages} pages for digital text vs image scans...")

            page_markdowns = [None] * total_pages
            scanned_page_indices = []

            # Step 1: Check cached pages on disk first
            cached_count = 0
            for p_idx in range(total_pages):
                p_cache_file = ocr_cache_dir / f"page_{p_idx+1:04d}.md"
                if p_cache_file.exists():
                    page_markdowns[p_idx] = p_cache_file.read_text(encoding="utf-8")
                    cached_count += 1
                else:
                    page = doc[p_idx]
                    p_text = page.get_text() or ""
                    images = page.get_images()

                    if len(p_text.strip()) < 100 and len(images) > 0:
                        scanned_page_indices.append(p_idx)
                    else:
                        # Digital text page -> extract with pymupdf4llm and checkpoint immediately
                        try:
                            p_md = pymupdf4llm.to_markdown(doc, pages=[p_idx])
                            page_markdowns[p_idx] = p_md
                        except Exception:
                            page_markdowns[p_idx] = p_text
                        
                        p_cache_file.write_text(page_markdowns[p_idx], encoding="utf-8")
                        cached_count += 1

            uncached_scans = [p for p in scanned_page_indices if page_markdowns[p] is None]
            print(f"[Smart Ingestion] Total Pages: {total_pages} | Cached/Digital: {cached_count} | Pending Scans: {len(uncached_scans)}")

            # Step 2: Process Pending Scanned Pages in Checkpointed Batches
            if uncached_scans:
                print(f"[Smart Ingestion - Vision OCR] Processing {len(uncached_scans)} pending scanned pages...")
                batch_size = 6
                client = None

                try:
                    import pypdf
                    import io
                    pypdf_reader = pypdf.PdfReader(str(file_path))

                    for i in range(0, len(uncached_scans), batch_size):
                        batch_indices = uncached_scans[i:i + batch_size]
                        print(f"  • OCR Batch for pages {[p+1 for p in batch_indices]}...")

                        if client is None:
                            client = get_gemini_client()

                        writer = pypdf.PdfWriter()
                        for p_idx in batch_indices:
                            writer.add_page(pypdf_reader.pages[p_idx])

                        pdf_bytes = io.BytesIO()
                        writer.write(pdf_bytes)
                        pdf_data = pdf_bytes.getvalue()

                        ocr_prompt = (
                            "You are an expert OCR transcription engine. "
                            "Transcribe all text, handwritten notes, mathematical equations, tables, and diagrams "
                            "from these scanned book pages into clean, highly structured Markdown. "
                            "Preserve all headings (#, ##), bullet points, and table formatting. Do not summarize."
                        )

                        resp = client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=[
                                types.Part.from_bytes(data=pdf_data, mime_type="application/pdf"),
                                ocr_prompt
                            ]
                        )
                        ocr_result = resp.text.strip()
                        
                        # Assign and persist checkpoint to disk immediately for every page in this batch
                        page_markdowns[batch_indices[0]] = ocr_result
                        (ocr_cache_dir / f"page_{batch_indices[0]+1:04d}.md").write_text(ocr_result, encoding="utf-8")
                        
                        for other_idx in batch_indices[1:]:
                            page_markdowns[other_idx] = ""
                            (ocr_cache_dir / f"page_{other_idx+1:04d}.md").write_text("", encoding="utf-8")

                except Exception as ex:
                    print(f"[Smart Ingestion - Cloud OCR Note] {ex}")
                    print(f"[Smart Ingestion - Local OCR Microservice] Delegating remaining pages to OCR Microservice (http://127.0.0.1:8088)...")
                    try:
                        from services.ocr_client import OCRServiceClient
                        ocr_client = OCRServiceClient()
                        ocr_client.ensure_daemon_running()
                        for p_idx in uncached_scans:
                            if page_markdowns[p_idx] is None:
                                page_text = ocr_client.transcribe_pdf_page(file_path, page_index=p_idx, dpi=180)
                                page_markdowns[p_idx] = page_text
                                (ocr_cache_dir / f"page_{p_idx+1:04d}.md").write_text(page_text, encoding="utf-8")
                                print(f"  • [OCR Microservice] Transcribed page {p_idx+1}/{total_pages} ({len(page_text)} chars)")
                    except Exception as local_ex:
                        print(f"[Smart Ingestion - OCR Microservice Error] {local_ex}")
                        for p_idx in uncached_scans:
                            if page_markdowns[p_idx] is None:
                                page_markdowns[p_idx] = doc[p_idx].get_text() or ""

            # Step 3: Assemble all available pages into book.md
            full_markdown = "\n\n".join([m for m in page_markdowns if m and m.strip()])
            try:
                book_md.write_text(full_markdown, encoding="utf-8")
                if not any(page_markdowns[p] is None for p in scanned_page_indices):
                    cache_md.write_text(full_markdown, encoding="utf-8")
                print(f"[Smart Ingestion] Successfully assembled & updated {book_md} ({len(full_markdown):,} chars)")
            except Exception:
                pass

            return full_markdown
        else:
            raise ValueError(f"Unsupported book format: '{suffix}'. Supported formats: .md, .txt, .pdf, .docx, .doc, .epub")

    @classmethod
    def parse_chapters(cls, file_path: Path) -> List[Dict]:
        """
        Heuristically discovers and segments all chapters in a book.
        Supports:
        - CHAPTER 1 / CHAPTER ONE / Chapter 1: <Title>
        - MODULE 1 / Unit 1 / Section 1
        - Roman numerals (CHAPTER I, Chapter IV)
        """
        full_text = cls.extract_full_text(file_path)
        
        # Word and Roman numeral mapping
        word_to_num = {
            'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
            'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
            'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15,
            'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20,
            'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5,
            'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10,
            'xi': 11, 'xii': 12, 'xiii': 13, 'xiv': 14, 'xv': 15,
            'xvi': 16, 'xvii': 17, 'xviii': 18, 'xix': 19, 'xx': 20
        }

        # Regex patterns to detect chapter start boundaries
        patterns = [
            r"(?:^|\n)(?:#{1,4}\s+)?\*{0,2}(?:CHAPTER|Chapter|MODULE|Module|UNIT|Unit|SECTION|Section)\s+([0-9a-zA-Z]+)\b[\:\.\*\s\-]*(.*?)(?=\n)",
            r"(?:^|\n)(?:#{1,4}\s+)?\*{0,2}([0-9]{1,2})\.1\s+(?:Learning\s+Objectives|Introduction|Meaning)\b[\:\.\*\s\-]*(.*?)(?=\n)"
        ]

        matches = []
        for pat in patterns:
            for m in re.finditer(pat, full_text):
                matches.append(m)

        # Remove duplicate matches at identical character positions
        unique_matches = []
        seen_pos = set()
        for m in matches:
            if m.start() not in seen_pos:
                seen_pos.add(m.start())
                unique_matches.append(m)
        
        unique_matches.sort(key=lambda x: x.start())

        raw_chapters = []
        if unique_matches:
            for idx, match in enumerate(unique_matches):
                ch_num_raw = match.group(1).strip()
                ch_title = match.group(2).strip(" *#:-") if len(match.groups()) > 1 and match.group(2) else ""
                
                # Convert string / Roman numeral / word to integer
                if ch_num_raw.isdigit():
                    ch_num = int(ch_num_raw)
                else:
                    ch_num = word_to_num.get(ch_num_raw.lower(), idx + 1)

                start_pos = match.start()
                end_pos = unique_matches[idx + 1].start() if idx + 1 < len(unique_matches) else len(full_text)
                ch_text = full_text[start_pos:end_pos].strip()

                if not ch_title or "...." in ch_title or ch_title.lower().startswith("after"):
                    # Look ahead on next lines for a title heading
                    lines = ch_text.splitlines()
                    for line in lines[:10]:
                        clean_l = line.strip(" *#:-_")
                        if (clean_l and 
                            not clean_l.lower().startswith("learning objectives") and 
                            not clean_l.lower().startswith("after") and 
                            "...." not in clean_l and 
                            not re.match(r"^(?:chapter|module|unit)\s+", clean_l, re.I) and
                            not re.match(r"^(?:[ivx]+\.|\([ivx]+\)|[0-9]+\.|\([0-9]+\)|[a-z]\.|\([a-z]\))\s*", clean_l, re.I) and
                            not re.match(r"^[0-9]+\.[0-9]+", clean_l)):
                            ch_title = clean_l
                            break
                    if not ch_title or "...." in ch_title or ch_title.lower().startswith("after"):
                        ch_title = f"Chapter {ch_num}"

                raw_chapters.append({
                    "number": ch_num,
                    "title": ch_title,
                    "text": ch_text,
                    "word_count": len(ch_text.split()),
                    "char_count": len(ch_text)
                })

        # Filter out Table of Contents duplicates (keep substantive chapters with higher word count)
        chapters = []
        seen_nums = {}
        for ch in raw_chapters:
            num = ch["number"]
            if num in seen_nums:
                existing_idx = seen_nums[num]
                if ch["word_count"] > chapters[existing_idx]["word_count"]:
                    chapters[existing_idx] = ch
            else:
                if ch["word_count"] > 150 or len(raw_chapters) == 1:
                    seen_nums[num] = len(chapters)
                    chapters.append(ch)

        # Sort chapters by number
        chapters.sort(key=lambda x: x["number"])
        return chapters

    @classmethod
    def get_chapter(cls, file_path: Path, chapter_num: int) -> Dict:
        """Retrieves a specific chapter by number."""
        chapters = cls.parse_chapters(file_path)
        for ch in chapters:
            if ch["number"] == chapter_num:
                return ch
        raise ValueError(f"Chapter {chapter_num} not found in {file_path}. (Available: {[c['number'] for c in chapters]})")


# ============================================================================
# 3. GRAPHRAG KNOWLEDGE GRAPH RETRIEVAL
# ============================================================================

def retrieve_graph_context(chapter_num: int, book_slug: str = "", graph_path: str = "graphify-out/graph.json") -> dict:
    """
    Queries the Graphify knowledge graph for deep structural connections,
    prerequisites from prior chapters, previews for upcoming chapters,
    and active hyperedges to inject into the audio lecture generation.
    """
    g_file = Path(graph_path)
    if not g_file.exists():
        return {"nodes": [], "relationships": [], "hyperedges": [], "summary": "No knowledge graph found."}

    data = json.loads(g_file.read_text(encoding="utf-8"))
    nodes_data = {n["id"]: n for n in data.get("nodes", [])}
    links = data.get("links", [])
    hyperedges = data.get("hyperedges", [])

    c_str = f"chapter_{chapter_num}"
    c_label = f"Chapter {chapter_num}"
    
    chapter_node_ids = set()
    for nid, ndata in nodes_data.items():
        lbl = ndata.get("label", "")
        source_file = ndata.get("source_file", "")
        # Filter by book slug if specified to prevent cross-book bleeding
        if book_slug and (book_slug not in nid.lower() and book_slug not in source_file.lower()):
            continue
        if c_str in nid.lower() or c_label.lower() in lbl.lower():
            chapter_node_ids.add(nid)

    # 1-hop subgraph relationships
    relationships = []
    prerequisites = []
    previews = []

    for link in links:
        u = link.get("source")
        v = link.get("target")
        if u in chapter_node_ids or v in chapter_node_ids:
            u_lbl = nodes_data.get(u, {}).get("label", u)
            v_lbl = nodes_data.get(v, {}).get("label", v)
            rel = link.get("relation", "relates_to")
            conf = link.get("confidence", "EXTRACTED")
            
            rel_str = f"{u_lbl} --[{rel} ({conf})]--> {v_lbl}"
            relationships.append(rel_str)
            
            for ch_prev in range(1, chapter_num):
                if f"chapter_{ch_prev}" in u.lower() or f"Chapter {ch_prev}" in u_lbl:
                    prerequisites.append(f"Chapter {ch_prev} Concept: {u_lbl}")
                elif f"chapter_{ch_prev}" in v.lower() or f"Chapter {ch_prev}" in v_lbl:
                    prerequisites.append(f"Chapter {ch_prev} Concept: {v_lbl}")

            for ch_next in range(chapter_num + 1, 20):
                if f"chapter_{ch_next}" in u.lower() or f"Chapter {ch_next}" in u_lbl:
                    previews.append(f"Future Chapter {ch_next} Preview: {u_lbl}")
                elif f"chapter_{ch_next}" in v.lower() or f"Chapter {ch_next}" in v_lbl:
                    previews.append(f"Future Chapter {ch_next} Preview: {v_lbl}")

    active_hyperedges = []
    for h in hyperedges:
        h_nodes = h.get("nodes", [])
        if any(hn in chapter_node_ids for hn in h_nodes):
            active_hyperedges.append(f"{h.get('label', h.get('id'))}: {', '.join([nodes_data.get(n, {}).get('label', n) for n in h_nodes])}")

    entities = []
    for nid in chapter_node_ids:
        nd = nodes_data.get(nid, {})
        lbl = nd.get("label", nid)
        rat = nd.get("rationale", "")
        rat_info = f" (Exam Rationale: {rat})" if rat else ""
        entities.append(f"{lbl}{rat_info}")

    return {
        "entities": entities[:30],
        "relationships": relationships[:25],
        "prerequisites": list(set(prerequisites))[:8],
        "previews": list(set(previews))[:8],
        "active_hyperedges": active_hyperedges[:5]
    }


def validate_script_against_graph(script: dict, graph_context: dict) -> dict:
    """Validates that key graph entities are covered in the generated audio script."""
    all_script_text = " ".join([s.get("text", "") for s in script.get("segments", []) if s.get("type") == "speech"]).lower()
    
    covered = []
    missing = []
    
    for entity in graph_context.get("entities", []):
        base_name = re.sub(r"\(.*?\)", "", entity).strip().lower()
        if len(base_name) > 3 and (base_name in all_script_text or any(w in all_script_text for w in base_name.split() if len(w) > 4)):
            covered.append(entity)
        else:
            missing.append(entity)

    coverage_pct = (len(covered) / max(1, len(covered) + len(missing))) * 100
    return {
        "coverage_pct": round(coverage_pct, 1),
        "covered_count": len(covered),
        "missing_count": len(missing),
        "covered_sample": covered[:6],
        "missing_sample": missing[:6]
    }


# ============================================================================
# 4. MASTERCLASS SCRIPT GENERATOR & DEEPER RESEARCH ENGINE
# ============================================================================

def get_gemini_client():
    from google import genai
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set. Please export GEMINI_API_KEY='your_api_key'")
    return genai.Client(api_key=api_key)


def sync_graphify_build(graph_path: str = "graphify-out/graph.json"):
    """Rebuilds Graphify clustering, report, and exports HTML visualization."""
    import subprocess
    py_path_file = Path("graphify-out/.graphify_python")
    py_bin = py_path_file.read_text().strip() if py_path_file.exists() else ".venv/bin/python"
    
    script = """
import json, networkx as nx
from pathlib import Path
from graphify.cluster import cluster, score_all
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.report import generate
from graphify.export import to_json

g_path = Path('graphify-out/graph.json')
if not g_path.exists():
    exit(0)

data = json.loads(g_path.read_text(encoding='utf-8'))
nodes_dict = {n['id']: n for n in data.get('nodes', [])}

G = nx.Graph()
for nid, nd in nodes_dict.items():
    G.add_node(nid, **nd)

for link in data.get('links', []):
    u = link.get('source')
    v = link.get('target')
    if u in nodes_dict and v in nodes_dict:
        G.add_edge(u, v, **link)

communities = cluster(G)
cohesion = score_all(G, communities)
gods = god_nodes(G)
surprises = surprising_connections(G, communities)

labels = json.loads(Path('graphify-out/.graphify_labels.json').read_text()) if Path('graphify-out/.graphify_labels.json').exists() else {}
labels = {int(k): v for k, v in labels.items()}
for cid in communities:
    if cid not in labels:
        labels[cid] = f'Community {cid}'

questions = suggest_questions(G, communities, labels)

to_json(G, communities, 'graphify-out/graph.json')
rep = generate(G, communities, cohesion, labels, gods, surprises, {'files': [], 'new_total': 0, 'total_files': len(nodes_dict), 'total_words': 100000, 'added': [], 'modified': []}, {'input': 0, 'output': 0}, '.', suggested_questions=questions)
Path('graphify-out/GRAPH_REPORT.md').write_text(rep, encoding='utf-8')
"""
    try:
        subprocess.run([py_bin, "-c", script], check=True, capture_output=True)
        subprocess.run([py_bin, "-m", "graphify", "export", "html"], check=True, capture_output=True)
        print("[Graphify] Successfully synced graph.json, GRAPH_REPORT.md, and graph.html!")
    except Exception as e:
        print(f"[Graphify] Note on build sync: {e}")


def index_book_to_graph(client, book_file: Path, metadata: BookMetadata, graph_path: str = "graphify-out/graph.json", deep_mode: bool = True) -> dict:
    """
    Extracts deep semantic knowledge graph entities, relationships, prerequisites,
    hyperedges, semantic similarities, and exam rationales across all chapters of a book in DEEP_MODE.
    """
    from google.genai import types
    chapters = UniversalBookParser.parse_chapters(book_file)
    print(f"\n[Graphify Indexer - DEEP MODE] Deeply indexing {len(chapters)} chapters for '{metadata.title}' into Knowledge Graph...")

    g_path = Path(graph_path)
    existing_data = json.loads(g_path.read_text(encoding="utf-8")) if g_path.exists() else {"nodes": [], "links": [], "hyperedges": []}
    
    existing_nodes = {n["id"]: n for n in existing_data.get("nodes", [])}
    existing_links = existing_data.get("links", [])
    existing_hyperedges = existing_data.get("hyperedges", [])
    
    for ch in chapters:
        ch_num = ch["number"]
        ch_title = ch["title"]
        ch_text = ch["text"][:14000] # Substantive chapter context
        
        print(f"  • Deep extraction for Chapter {ch_num}: {ch_title}...")
        prompt = f"""
You are an expert knowledge graph extraction agent for Graphify running in DEEP_MODE.
Extract a rich, comprehensive knowledge graph fragment for Chapter {ch_num} ({ch_title}) of '{metadata.title}'.

DEEP_MODE EXTRACTION RULES:
1. Nodes:
   - Extract all named concepts, formulas, methodologies, classifications, variables, case studies, distributions, and exam rationales in Chapter {ch_num}.
   - id: snake_case string strictly prefixed with '{metadata.slug}_ch{ch_num}_' (e.g. '{metadata.slug}_ch{ch_num}_descriptive_statistics')
   - label: Clear human-readable name
   - file_type: 'concept' or 'document'
   - source_file: 'books/{metadata.slug}/book.md'
   - source_location: 'Chapter {ch_num}'
   - rationale: Detailed exam justification, practical HR/business application, or why this concept matters.

2. Edges (Aggressive INFERRED and Structural Relationships):
   - Be aggressive with INFERRED relationships: prerequisite dependencies, shared assumptions, latent couplings, formula derivations, and contrasted concepts.
   - For EXTRACTED edges: confidence='EXTRACTED', confidence_score=1.0
   - For INFERRED edges: confidence='INFERRED', confidence_score from [0.95, 0.85, 0.75, 0.65]
   - Relations: 'prerequisite_for', 'conceptually_related_to', 'contains', 'calculates', 'contrasted_with', 'applies_to', 'semantically_similar_to', 'rationale_for'

3. Hyperedges:
   - If 3 or more concepts participate together in a shared process, formula pipeline, or framework, define a hyperedge.

Output ONLY valid JSON with no markdown fences:
{{
  "nodes": [
    {{"id": "...", "label": "...", "file_type": "concept", "source_file": "books/{metadata.slug}/book.md", "source_location": "Chapter {ch_num}", "rationale": "..."}}
  ],
  "edges": [
    {{"source": "...", "target": "...", "relation": "...", "confidence": "EXTRACTED|INFERRED", "confidence_score": 1.0}}
  ],
  "hyperedges": [
    {{"id": "...", "label": "...", "nodes": ["...", "..."], "relation": "participate_in"}}
  ]
}}
"""
        try:
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[prompt, f"Chapter Text:\n{ch_text}"],
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            data = json.loads(resp.text.strip())
            
            # Merge nodes
            for n in data.get("nodes", []):
                existing_nodes[n["id"]] = n
                
            # Merge edges
            for e in data.get("edges", []):
                link_obj = {
                    "source": e.get("source"),
                    "target": e.get("target"),
                    "relation": e.get("relation", "conceptually_related_to"),
                    "confidence": e.get("confidence", "EXTRACTED"),
                    "confidence_score": e.get("confidence_score", 1.0),
                    "source_file": f"books/{metadata.slug}/book.md",
                    "weight": 1.0
                }
                existing_links.append(link_obj)

            # Merge hyperedges
            for h in data.get("hyperedges", []):
                existing_hyperedges.append(h)
        except Exception as ex:
            print(f"    [Warning] Extraction note on Chapter {ch_num}: {ex}")

    # Remove duplicate links
    seen_links = set()
    unique_links = []
    for l in existing_links:
        pair = (l.get("source"), l.get("target"), l.get("relation"))
        if pair not in seen_links and l.get("source") in existing_nodes and l.get("target") in existing_nodes:
            seen_links.add(pair)
            unique_links.append(l)

    # Save merged graph
    g_path.parent.mkdir(parents=True, exist_ok=True)
    out_graph = {
        "nodes": list(existing_nodes.values()),
        "links": unique_links,
        "hyperedges": existing_hyperedges
    }
    g_path.write_text(json.dumps(out_graph, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[Graphify Indexer - DEEP MODE] Successfully merged {len(existing_nodes)} nodes and {len(unique_links)} links into {g_path}")
    
    # Rebuild clusters and export HTML visualization
    sync_graphify_build(graph_path)
    return out_graph


def research_book_blueprint(client, book_file: Path, metadata: BookMetadata) -> str:
    """
    Performs deep pedagogical research on a specific textbook, indexes it into
    Graphify knowledge graph, and generates books/<slug>/deeper-research-report.md.
    """
    from google.genai import types
    print(f"\n[Deeper Research Engine] Conducting deep pedagogical research for '{metadata.title}'...")
    
    full_text = UniversalBookParser.extract_full_text(book_file)
    sample_text = full_text[:40000] # First ~8,000 words covering TOC and early chapters
    
    system_prompt = f"""
You are a distinguished educational cognitive scientist and masterclass pedagogical architect.
Your task is to conduct a DEEP PEDAGOGICAL RESEARCH STUDY on the professional textbook:
'{metadata.title}' (Examining Body / Field: {metadata.exam_body}, Target Audience: {metadata.target_audience}).

Your goal is to produce a comprehensive, master-level markdown dossier titled:
'# Deeper Pedagogical Research Report & Assimilation Blueprint: {metadata.title}'

This document will serve as the specialized pedagogical guide used by AI scriptwriters and lecturers to generate world-class spoken audio masterclasses for EVERY chapter in this book.

Your report MUST be deep, authoritative, and exhaustive, covering:

1. EXECUTIVE SUMMARY & SUBJECT-SPECIFIC LEARNING SCIENCE
   - Cognitive architecture of learning in this specific discipline ({metadata.title}).
   - How adult candidates assimilate this material (e.g. overcoming math anxiety, abstract conceptualization, statutory interpretation, or procedural design).
   - Core failure modes and misconceptions students make in this examination.

2. SPOKEN-WORD TRANSLATION RULES & AUDIO MODALITY
   - Specify the exact Spoken Pedagogical Modality (Quantitative & Statistical, Conceptual & Organizational, Legal & Regulatory, or Procedural & Methodological).
   - Provide concrete rules for translating discipline-specific symbols, jargon, formulas, or statutory citations into natural, engaging spoken English.
   - For Quantitative books: Define the 'Spoken Formula Intuition' rule (explain conceptual meaning in plain words before computing).
   - For Management/Communication: Define the 'Workplace Scenario & Behavioral Dynamic' rule.
   - For Law/Governance: Define the 'IRAC Case Law & Statutory Analysis' rule.

3. SUBJECT-SPECIFIC MENTAL MODELS, ANALOGIES & MNEMONICS
   - 4 to 6 powerful physical analogies, mental models, and memory devices tailored specifically to the concepts in this book.

4. CURRICULUM ARCHITECTURE & PREREQUISITE DEPENDENCY MAP
   - Map out the progression of all chapters in the book.
   - Identify foundational 'god-nodes' in early chapters that future chapters depend upon.

5. HIGH-YIELD EXAM TRAPS & DISTINCTIONS
   - 5 to 10 classic exam traps, confusing pairs, and high-frequency distinction questions candidates encounter in this subject.

Format with rich Markdown, clear headings, callouts, and concrete examples.
"""

    prompt = f"Textbook Sample & Chapter Overview:\n\n{sample_text}"

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[system_prompt, prompt],
        config=types.GenerateContentConfig(temperature=0.7)
    )

    report_text = response.text.strip()
    book_dir = book_file.parent if book_file.is_file() else book_file
    out_path = book_dir / "deeper-research-report.md"
    out_path.write_text(report_text, encoding="utf-8")
    print(f"[DONE] Specialized deeper research report saved to: {out_path}")
    
    # Auto-index book into Graphify knowledge graph
    try:
        index_book_to_graph(client, book_file, metadata)
    except Exception as e:
        print(f"[Graphify] Note during auto-indexing: {e}")

    return report_text


def generate_pedagogical_script_gemini(
    client, 
    chapter_data: Dict, 
    metadata: BookMetadata, 
    target_duration_mins: int = 30, 
    graph_context: Optional[dict] = None
) -> dict:
    """
    Transforms dense academic text into an unhurried, conversational spoken script
    adhering to the Universal Masterclass Architecture and book-specific blueprint.
    """
    from google.genai import types

    # Load book-specific deeper research report if present
    book_dir = metadata.book_path.parent if metadata.book_path.is_file() else metadata.book_path
    deeper_report_path = book_dir / "deeper-research-report.md"
    deeper_context = ""
    if deeper_report_path.exists():
        deeper_context = f"""
SPECIALIZED BOOK PEDAGOGY BLUEPRINT ({metadata.title}):
{deeper_report_path.read_text(encoding='utf-8')[:8000]}
"""

    graph_section = ""
    if graph_context and graph_context.get("entities"):
        entities_str = "\n".join([f"   * {e}" for e in graph_context.get("entities", [])])
        relations_str = "\n".join([f"   * {r}" for r in graph_context.get("relationships", [])[:15]])
        prereq_str = "\n".join([f"   * {p}" for p in graph_context.get("prerequisites", [])]) if graph_context.get("prerequisites") else "   * None (Foundational chapter)"
        preview_str = "\n".join([f"   * {p}" for p in graph_context.get("previews", [])]) if graph_context.get("previews") else "   * General upcoming topics"

        graph_section = f"""
KNOWLEDGE GRAPH CONTEXT (Syllabus Connections):
- Key Entities & Exam Rationales to explicitly cover:
{entities_str}
- Prior Chapter Prerequisites (use for quick active-recall callbacks):
{prereq_str}
- Upcoming Chapter Previews (use for forward signposting):
{preview_str}
- Inferred & Structural Relationships:
{relations_str}
"""

    system_instruction = f"""
You are an award-winning educational lecturer and masterclass podcaster transforming the professional textbook '{metadata.title}' (Target Audience: {metadata.target_audience}, Examining Body: {metadata.exam_body}) into an engaging, unhurried, high-yield audio masterclass.

NON-NEGOTIABLE CORE MASTERCLASS LAWS:
1. ZERO ARTIFICIAL DURATION LIMITS (NO ARBITRARY TRUNCATION):
   - Audio duration is completely unconstrained. A chapter masterclass must run as long as required for 100% textbook coverage (whether 1 hour, 2.5 hours, 5 hours, or 10+ hours).
   - Never summarize, drop subsections, or compress away granular textbook details to meet an artificial time ceiling.
   - Every single heading, sub-heading, author citation, definition, category, classification table, legal nuance, feasibility component, and practice MCQ from the textbook must be fully unpacked, illustrated, and taught.

2. ONE CHAPTER = ONE UNIFIED MASTERCLASS AUDIO:
   - The entire chapter must be completely contained in this single script and synthesized into one unified masterclass audio file.

3. COGNITIVE CHUNKING VIA FREQUENT EMBEDDED MODULAR STUDY BREAKS:
   - To manage listener working memory across long comprehensive sessions, embed frequent Modular Study Break Checkpoints (every 10–15 minutes of speech).
   - At each checkpoint, provide a warm, natural transition inviting the listener to pause, review notes, or take a break, followed by an explicit pause block (duration_seconds: 5 to 10).

4. UNCOMPROMISED DEEP-DIVE PEDAGOGICAL MENTAL MODELS:
   - The core narrative frameworks (e.g. The Three-Legged Stool, Salomon v Salomon, The Failure Iceberg, The Stakeholder Spiderweb, Spoken Formula Intuition, Workplace Scenarios) must remain the primary teaching vehicle and never be diluted.

5. DISTRIBUTED ACTIVE RECALL THROUGHOUT:
   - Intersperse active-recall micro-questions throughout the lecture (every 3–5 minutes).
   - After each question, insert an explicit pause block (duration_seconds: 4) before revealing the model answer.

6. CASE STUDY & EXAM REVIEW INTEGRATION:
   - Walk through all official case studies, theory review questions, and multiple-choice questions (MCQs) in the textbook chapter with full explanations and exam justifications.

7. THREE-LAYER FINAL CONSOLIDATION:
   - Layer 1: Rapid 5-point structural synthesis.
   - Layer 2: High-yield exam distinctions ("Don't confuse X with Y").
   - Layer 3: Spaced-recall prompt and forward bridge into the next chapter.

{deeper_context}

{graph_section}

OUTPUT FORMAT:
Output MUST be a valid JSON object matching this schema:
{{
  "title": "{metadata.title} - Chapter {chapter_data['number']}: {chapter_data['title']}",
  "chapter_number": {chapter_data['number']},
  "estimated_duration_mins": {target_duration_mins},
  "segments": [
    {{
      "type": "speech",
      "text": "Spoken text here...",
      "section_label": "Intro / Objective / Concept 1 / etc."
    }},
    {{
      "type": "pause",
      "duration_seconds": 4,
      "purpose": "reflection on quiz question"
    }}
  ]
}}
DO NOT include markdown fences around the JSON, just pure JSON.
"""

    prompt = f"""
Please convert the following complete chapter text from '{metadata.title}' into an in-depth pedagogical audio masterclass script:

--- CHAPTER {chapter_data['number']}: {chapter_data['title']} START ---
{chapter_data['text']}
--- CHAPTER END ---
"""

    max_retries = 5
    response = None
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[system_instruction, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.7
                )
            )
            break
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait_secs = 50 if attempt == 0 else (attempt + 1) * 25
                print(f"[Rate Limit] Gemini API quota window active. Waiting {wait_secs}s before retry (Attempt {attempt+1}/{max_retries})...")
                time.sleep(wait_secs)
            else:
                raise e

    if not response or not response.text:
        raise RuntimeError("Failed to generate pedagogical script after retry attempts.")

    text_resp = response.text.strip()
    if text_resp.startswith("```json"):
        text_resp = text_resp[7:]
    if text_resp.endswith("```"):
        text_resp = text_resp[:-3]

    return json.loads(text_resp)


# ============================================================================
# 5. SPEECH SYNTHESIS ENGINE
# ============================================================================

def synthesize_speech_gemini(client, text: str, voice_name: str = "Puck") -> AudioSegment:
    """Synthesizes text using Gemini native TTS."""
    from google.genai import types
    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name
                    )
                )
            )
        )
    )

    pcm_data = None
    for part in response.candidates[0].content.parts:
        if part.inline_data:
            pcm_data = part.inline_data.data
            break

    if not pcm_data:
        raise RuntimeError("No audio data returned by Gemini TTS")

    wav_io = io.BytesIO()
    with wave.open(wav_io, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(pcm_data)

    wav_io.seek(0)
    return AudioSegment.from_wav(wav_io)


async def synthesize_speech_edge(text: str, voice_name: str = "en-NG-AbeoNeural", rate: str = "-18%") -> AudioSegment:
    """Synthesizes text using Microsoft Edge Neural TTS with automatic retries and rate control."""
    import edge_tts
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            communicate = edge_tts.Communicate(text, voice_name, rate=rate)
            mp3_io = io.BytesIO()
            has_audio = False
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3_io.write(chunk["data"])
                    has_audio = True
            if has_audio:
                mp3_io.seek(0)
                return AudioSegment.from_file(mp3_io, format="mp3")
            else:
                raise RuntimeError("No audio chunk received from stream")
        except Exception as e:
            if attempt == max_retries:
                raise e
            await asyncio.sleep(1.0 * attempt)


def build_lecture_audio(
    client, 
    script_data: dict, 
    output_audio_path: Path, 
    engine: str = "edge", 
    voice_name: str = "en-NG-AbeoNeural", 
    rate: str = "-18%"
) -> Path:
    """Builds complete audio track by synthesizing speech segments and inserting silent pauses."""
    combined_audio = AudioSegment.silent(duration=500)
    segments = script_data.get("segments") or script_data.get("blocks") or []
    total_segments = len(segments)

    print(f"Synthesizing audio for {total_segments} script blocks (Engine: {engine.upper()}, Voice: {voice_name}, Rate: {rate})...")

    for idx, seg in enumerate(segments, 1):
        seg_type = seg.get("type")
        if seg_type == "speech":
            text = seg.get("text", "").strip()
            if not text:
                continue
            label = seg.get("section_label") or seg.get("section") or "Speech"
            print(f"  [{idx}/{total_segments}] Synthesizing ({label}): {text[:50]}...")
            
            if engine == "gemini":
                speech_clip = synthesize_speech_gemini(client, text, voice_name=voice_name)
            else:
                speech_clip = asyncio.run(synthesize_speech_edge(text, voice_name=voice_name, rate=rate))
            
            combined_audio += speech_clip
            combined_audio += AudioSegment.silent(duration=400)

        elif seg_type == "pause":
            pause_sec = seg.get("duration_seconds", 3)
            print(f"  [{idx}/{total_segments}] Inserting {pause_sec}s reflection pause...")
            combined_audio += AudioSegment.silent(duration=int(pause_sec * 1000))

    combined_audio += AudioSegment.silent(duration=1000)

    output_audio_path.parent.mkdir(parents=True, exist_ok=True)
    combined_audio.export(str(output_audio_path), format="mp3", bitrate="192k")
    
    total_sec = len(combined_audio) / 1000.0
    print(f"\n[DONE] Lecture audio saved to: {output_audio_path}")
    print(f"Total Duration: {total_sec:.1f} seconds ({total_sec / 60.0:.2f} mins)")
    return output_audio_path


def save_transcript_markdown(script_data: dict, output_md_path: Path):
    """Saves formatted lecture transcript and study guide."""
    lines = [
        f"# Audio Masterclass: {script_data.get('title', 'Chapter Masterclass')}",
        f"**Chapter:** {script_data.get('chapter') or script_data.get('chapter_number')}  ",
        f"**Estimated Duration:** ~{script_data.get('estimated_duration_mins')} minutes  ",
        "\n---\n",
        "## Masterclass Script & Interactive Checkpoints\n"
    ]

    segments = script_data.get("segments") or script_data.get("blocks") or []
    for seg in segments:
        if seg.get("type") == "speech":
            label = seg.get("section_label") or seg.get("section") or "Masterclass"
            lines.append(f"**[{label}]**  ")
            lines.append(f"{seg.get('text')}\n")
        elif seg.get("type") == "pause":
            lines.append(f"> ⏱️ *[Active Recall Pause: {seg.get('duration_seconds', 4)} seconds - {seg.get('purpose', 'Reflection pause')}...]*\n")

    output_md_path.parent.mkdir(parents=True, exist_ok=True)
    output_md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[DONE] Transcript saved to: {output_md_path}")


# ============================================================================
# 6. MAIN CLI WORKFLOW
# ============================================================================

def list_books():
    """Lists all available books in books/ directory."""
    books_dir = Path("books")
    if not books_dir.exists():
        print("No books/ directory found.")
        return
    print("Available Books in Catalog:")
    found = False
    for b in sorted(books_dir.iterdir()):
        if b.is_dir():
            cfg_file = b / "book_config.json"
            cfg = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
            title = cfg.get("book_title", b.name.replace("_", " ").title())
            exam = cfg.get("exam_body", "General")
            print(f"  • [{b.name}] {title} (Exam Body: {exam})")
            found = True
    if not found:
        print("  (No books found in books/ directory yet. Add a folder with book.md or book.pdf)")


def main():
    parser = argparse.ArgumentParser(description="Universal Multi-Book Pedagogical Audio Lecture Generation Engine.")
    parser.add_argument("--book", type=str, default=None, help="Path to book file (.pdf/.md) or folder/slug in books/ (default: auto-detect)")
    parser.add_argument("--chapter", type=int, default=1, help="Chapter number to generate (default: 1)")
    parser.add_argument("--all-chapters", action="store_true", help="Generate all chapters in the book sequentially")
    parser.add_argument("--list-chapters", action="store_true", help="List all detected chapters and word counts in the book")
    parser.add_argument("--list-books", action="store_true", help="List all books available in books/ catalog")
    parser.add_argument("--research-book", action="store_true", help="Conduct deep pedagogical research and generate books/<slug>/deeper-research-report.md")
    parser.add_argument("--index-book", action="store_true", help="Index all chapters of this book into the Graphify knowledge graph")
    parser.add_argument("--sync-graph", action="store_true", help="Rebuild graph clusters and export graph.html")
    parser.add_argument("--model", type=str, default=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"), help="Gemini model name (default: gemini-2.5-flash or gemini-3.7-flash)")
    parser.add_argument("--duration", type=int, default=30, help="Target duration in minutes (default: 30)")
    parser.add_argument("--engine", type=str, default="edge", choices=["gemini", "edge"], help="TTS engine ('gemini' or 'edge')")
    parser.add_argument("--voice", type=str, default="en-NG-AbeoNeural", help="Voice name (default: en-NG-AbeoNeural for Nigerian English Male, or en-NG-EzinneNeural for Female)")
    parser.add_argument("--rate", type=str, default="-18%", help="Speech rate adjustment (default: -18% for 100-110 WPM)")
    parser.add_argument("--script-file", type=str, default=None, help="Path to pre-existing script JSON (optional)")
    parser.add_argument("--graph-path", type=str, default="graphify-out/graph.json", help="Path to graph.json")
    parser.add_argument("--no-graph", action="store_true", help="Disable Graphify knowledge graph context injection")
    parser.add_argument("--outdir", type=str, default="output_lectures", help="Base output directory")
    args = parser.parse_args()

    if args.list_books:
        list_books()
        return

    if args.sync_graph:
        sync_graphify_build(args.graph_path)
        return

    # 1. Resolve Book File & Metadata
    book_file, metadata = resolve_book(args.book)
    print(f"\n=======================================================")
    print(f"Universal Audio Masterclass Engine")
    print(f"Book:   {metadata.title}")
    print(f"Source: {book_file}")
    print(f"Slug:   {metadata.slug}")
    print(f"=======================================================")

    # 1b. Deep Pedagogical Research Mode
    if args.research_book:
        client = get_gemini_client()
        research_book_blueprint(client, book_file, metadata)
        return

    # 1c. Knowledge Graph Indexing Mode
    if args.index_book:
        client = get_gemini_client()
        index_book_to_graph(client, book_file, metadata, graph_path=args.graph_path)
        return

    # 2. List Chapters Mode
    if args.list_chapters:
        chapters = UniversalBookParser.parse_chapters(book_file)
        print(f"\nFound {len(chapters)} Chapters in '{metadata.title}':")
        for ch in chapters:
            print(f"  Chapter {ch['number']:2d}: {ch['title']:<50} ({ch['word_count']:,} words)")
        return

    # Determine Chapters to process
    if args.all_chapters:
        all_ch = UniversalBookParser.parse_chapters(book_file)
        chapter_nums = [c["number"] for c in all_ch]
    else:
        chapter_nums = [args.chapter]

    out_base = Path(args.outdir) / metadata.slug
    out_base.mkdir(parents=True, exist_ok=True)

    for ch_num in chapter_nums:
        print(f"\n>>> Processing Chapter {ch_num} for '{metadata.title}' <<<")
        chapter_data = UniversalBookParser.get_chapter(book_file, ch_num)
        print(f"Chapter Title: {chapter_data['title']} ({chapter_data['word_count']:,} words)")

        # 3. Retrieve Graph Context
        graph_context = None
        if not args.no_graph:
            print(f"\n[Graphify] Querying knowledge graph for Chapter {ch_num}...")
            graph_context = retrieve_graph_context(ch_num, book_slug=metadata.slug, graph_path=args.graph_path)
            print(f"  • Retrieved {len(graph_context.get('entities', []))} syllabus entities")
            print(f"  • Retrieved {len(graph_context.get('relationships', []))} graph links")

        # 4. Generate or Load Script
        if args.script_file and os.path.exists(args.script_file):
            print(f"Loading script from {args.script_file}...")
            script_data = json.loads(Path(args.script_file).read_text(encoding="utf-8"))
        else:
            client = get_gemini_client()
            print(f"Stage 1: Generating Uncompressed Pedagogical Script with Gemini Flash...")
            script_data = generate_pedagogical_script_gemini(client, chapter_data, metadata, target_duration_mins=args.duration, graph_context=graph_context)
            
            script_json_path = out_base / f"chapter_{ch_num}_script.json"
            script_json_path.write_text(json.dumps(script_data, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Script saved to {script_json_path}")

        # 5. Validate Graph Coverage
        if graph_context and graph_context.get("entities"):
            val = validate_script_against_graph(script_data, graph_context)
            print(f"\n[Graph Coverage Gate]: {val['coverage_pct']}% of syllabus entities covered ({val['covered_count']}/{val['covered_count'] + val['missing_count']})")
            if val["missing_sample"]:
                print(f"  (Uncovered sample: {', '.join(val['missing_sample'])})")

        # 6. Save Transcript
        transcript_path = out_base / f"chapter_{ch_num}_transcript.md"
        save_transcript_markdown(script_data, transcript_path)

        # 7. Synthesize Audio
        print(f"\nStage 2: Synthesizing Audio (Voice: {args.voice}, Rate: {args.rate})...")
        audio_path = out_base / f"chapter_{ch_num}_lecture.mp3"
        client = get_gemini_client() if args.engine == "gemini" else None
        build_lecture_audio(client, script_data, audio_path, engine=args.engine, voice_name=args.voice, rate=args.rate)

        # 8. Automated Post-Chapter Knowledge Graph Synchronization
        print(f"\n[Graphify] Running automated post-chapter knowledge graph update for Chapter {ch_num}...")
        sync_graphify_build(args.graph_path)


if __name__ == "__main__":
    main()
