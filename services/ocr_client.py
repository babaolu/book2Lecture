import time
import subprocess
import requests
from pathlib import Path
from typing import Optional, Dict

class OCRServiceClient:
    """
    Decoupled client interface for communicating with the local OCR Microservice.
    Handles automatic daemon lifecycle (spawning background FastAPI server on demand).
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8088", auto_start: bool = True):
        self.base_url = base_url.rstrip("/")
        self.auto_start = auto_start
        self._daemon_process = None

    def is_healthy(self) -> bool:
        """Checks if the OCR microservice daemon is alive and healthy."""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=1.5)
            return resp.status_code == 200 and resp.json().get("status") == "healthy"
        except Exception:
            return False

    def ensure_daemon_running(self, timeout_seconds: int = 15) -> bool:
        """Ensures the OCR microservice is running, auto-spawning it as a background daemon if needed."""
        if self.is_healthy():
            return True

        if not self.auto_start:
            return False

        print(f"[OCR Client] OCR Microservice not detected on {self.base_url}. Auto-spawning background daemon...")
        cmd = [
            ".venv/bin/python", "-m", "uvicorn", 
            "services.ocr_service.app:app", 
            "--host", "127.0.0.1", 
            "--port", "8088", 
            "--log-level", "warning"
        ]
        
        self._daemon_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        # Poll until healthy
        t_start = time.time()
        while time.time() - t_start < timeout_seconds:
            if self.is_healthy():
                print(f"[OCR Client] OCR Microservice daemon successfully started on {self.base_url}!")
                return True
            time.sleep(0.5)

        print("[OCR Client - Warning] Could not verify OCR daemon health within timeout.")
        return False

    def transcribe_page_image(self, image_bytes: bytes, page_num: Optional[int] = None) -> str:
        """Sends raw image bytes to OCR microservice and returns formatted Markdown."""
        self.ensure_daemon_running()
        files = {"file": ("page.png", image_bytes, "image/png")}
        params = {"page_num": page_num} if page_num else {}
        
        resp = requests.post(f"{self.base_url}/v1/ocr/page", files=files, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("markdown", "")

    def transcribe_pdf_page(self, pdf_path: Path, page_index: int, dpi: int = 180) -> str:
        """Instructs OCR microservice to render and transcribe a single page from a local PDF."""
        self.ensure_daemon_running()
        params = {
            "pdf_path": str(pdf_path.resolve()),
            "page_index": page_index,
            "dpi": dpi
        }
        resp = requests.post(f"{self.base_url}/v1/ocr/pdf_page", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("markdown", "")
