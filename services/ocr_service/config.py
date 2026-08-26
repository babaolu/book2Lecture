import os
from pathlib import Path

OCR_HOST = os.environ.get("OCR_HOST", "127.0.0.1")
OCR_PORT = int(os.environ.get("OCR_PORT", 8088))
DEFAULT_DPI = int(os.environ.get("OCR_DPI", 180))

# Model Cache Directory
MODEL_CACHE_DIR = Path(os.environ.get("OCR_MODEL_DIR", Path.home() / ".cache" / "book2lecture_ocr"))
MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
