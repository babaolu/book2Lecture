import time
import sys
import pypdf
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ocr_client import OCRServiceClient
from lecture_generator import UniversalBookParser

def main():
    pdf_path = Path("books/fundamentals_of_economics/FUNDAMENTALS OF ECONOMICS (INTERMEDIATE 1).pdf")
    ocr_cache_dir = Path("books/fundamentals_of_economics/.ocr_cache")
    book_md = Path("books/fundamentals_of_economics/book.md")
    marker_file = Path("books/fundamentals_of_economics/FUNDAMENTALS OF ECONOMICS (INTERMEDIATE 1).extracted.md")
    
    ocr_cache_dir.mkdir(parents=True, exist_ok=True)
    
    reader = pypdf.PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    print(f"=== FULL-BOOK OCR INGESTION: FUNDAMENTALS OF ECONOMICS ({total_pages} PAGES) ===")
    
    client = OCRServiceClient()
    client.ensure_daemon_running()
    
    page_markdowns = [None] * total_pages
    cached_count = 0
    newly_ocr_count = 0
    t_start = time.time()
    
    for p_idx in range(total_pages):
        p_num = p_idx + 1
        p_cache = ocr_cache_dir / f"page_{p_num:04d}.md"
        
        if p_cache.exists() and p_cache.stat().st_size > 50:
            page_markdowns[p_idx] = p_cache.read_text(encoding="utf-8")
            cached_count += 1
        else:
            try:
                txt = client.transcribe_pdf_page(pdf_path, page_index=p_idx, dpi=180)
                if not txt or len(txt.strip()) < 10:
                    txt = reader.pages[p_idx].extract_text() or ""
                
                page_markdowns[p_idx] = txt
                p_cache.write_text(txt, encoding="utf-8")
                newly_ocr_count += 1
                
                if newly_ocr_count % 10 == 0 or p_num == total_pages:
                    elapsed = time.time() - t_start
                    pct = (p_num / total_pages) * 100
                    print(f"  • Progress: Page {p_num}/{total_pages} ({pct:.1f}%) | Cached: {cached_count} | New OCR: {newly_ocr_count} | Elapsed: {elapsed:.1f}s")
            except Exception as e:
                print(f"  [Warning] Error on page {p_num}: {e}")
                fallback_txt = reader.pages[p_idx].extract_text() or ""
                page_markdowns[p_idx] = fallback_txt
                p_cache.write_text(fallback_txt, encoding="utf-8")

    # Assemble into full book.md
    full_markdown = "\n\n---\n\n".join([m for m in page_markdowns if m and m.strip()])
    book_md.write_text(full_markdown, encoding="utf-8")
    marker_file.write_text(full_markdown, encoding="utf-8")
    
    total_words = len(full_markdown.split())
    total_chars = len(full_markdown)
    elapsed_total = time.time() - t_start
    
    print("\n" + "="*60)
    print(f"✅ FULL-BOOK OCR INGESTION COMPLETE!")
    print(f"Total Pages Processed: {total_pages}")
    print(f"book.md Characters:    {total_chars:,}")
    print(f"book.md Words:         {total_words:,}")
    print(f"Output File:           {book_md}")
    print(f"Extraction Marker:     {marker_file}")
    print(f"Total Time Taken:      {elapsed_total:.1f} seconds")
    print("="*60)
    
    # Parse discovered chapters
    chapters = UniversalBookParser.parse_chapters(book_md)
    print(f"\nDiscovered {len(chapters)} Chapters in Ingested Textbook:")
    for ch in chapters:
        print(f"  • Chapter {ch['number']}: {ch['title']} ({ch['word_count']:,} words)")

if __name__ == "__main__":
    main()
