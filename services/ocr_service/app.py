from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict
import fitz # PyMuPDF
from pathlib import Path
import io

from services.ocr_service.pipeline import LocalOCRPipeline
from services.ocr_service.config import OCR_HOST, OCR_PORT, DEFAULT_DPI

app = FastAPI(
    title="book2Lecture Local OCR Microservice",
    version="1.0.0",
    description="Decoupled standalone microservice for high-throughput layout analysis, text extraction, and Math/LaTeX OCR."
)

pipeline = LocalOCRPipeline.get_instance()

class OCRResponse(BaseModel):
    success: bool
    markdown: str
    char_count: int
    line_count: int
    elapse_seconds: float
    page_number: Optional[int] = None

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    engine: str

@app.get("/health", response_model=HealthResponse)
def health_check():
    """Health check endpoint for daemon monitoring."""
    return {
        "status": "healthy",
        "service": "book2lecture-ocr",
        "version": "1.0.0",
        "engine": "RapidOCR-ONNX"
    }

@app.post("/v1/ocr/page", response_model=OCRResponse)
async def ocr_image_page(file: UploadFile = File(...), page_num: Optional[int] = Query(None)):
    """Transcribes an uploaded page image (PNG/JPEG) into structured Markdown."""
    try:
        image_bytes = await file.read()
        res = pipeline.process_image_bytes(image_bytes)
        return {
            "success": True,
            "markdown": res["markdown"],
            "char_count": res["char_count"],
            "line_count": res["line_count"],
            "elapse_seconds": res["elapse_seconds"],
            "page_number": page_num
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/ocr/pdf_page", response_model=OCRResponse)
def ocr_pdf_page(pdf_path: str, page_index: int, dpi: int = DEFAULT_DPI):
    """Renders and transcribes a single page from a local PDF path."""
    p_path = Path(pdf_path)
    if not p_path.exists():
        raise HTTPException(status_code=404, detail=f"PDF file not found: {pdf_path}")
    
    try:
        doc = fitz.open(str(p_path))
        if page_index < 0 or page_index >= len(doc):
            raise HTTPException(status_code=400, detail=f"Page index {page_index} out of range (0-{len(doc)-1})")
        
        page = doc[page_index]
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("png")
        
        res = pipeline.process_image_bytes(img_bytes)
        return {
            "success": True,
            "markdown": res["markdown"],
            "char_count": res["char_count"],
            "line_count": res["line_count"],
            "elapse_seconds": res["elapse_seconds"],
            "page_number": page_index + 1
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("services.ocr_service.app:app", host=OCR_HOST, port=OCR_PORT, reload=False)
