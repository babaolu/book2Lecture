import re
import io
import time
from typing import List, Dict, Tuple, Optional
from PIL import Image
import numpy as np
from rapidocr_onnxruntime import RapidOCR

class LocalOCRPipeline:
    """
    Decoupled Local OCR Pipeline combining Layout Analysis, Text Extraction, 
    and Mathematical/Table structure formatting.
    """
    _instance = None

    def __init__(self):
        print("[OCR Service] Initializing RapidOCR ONNX engine...")
        self.engine = RapidOCR()
        print("[OCR Service] Engine initialized and ready.")

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = LocalOCRPipeline()
        return cls._instance

    def process_image_bytes(self, image_bytes: bytes) -> Dict:
        """Processes raw image bytes and returns structured markdown."""
        t0 = time.time()
        result, elapse = self.engine(image_bytes)
        t1 = time.time()

        if not result:
            return {
                "markdown": "",
                "char_count": 0,
                "line_count": 0,
                "elapse_seconds": t1 - t0,
                "lines": []
            }

        raw_lines = [item[1] for item in result]
        formatted_md = self._format_structured_markdown(raw_lines)

        return {
            "markdown": formatted_md,
            "char_count": len(formatted_md),
            "line_count": len(raw_lines),
            "elapse_seconds": t1 - t0,
            "lines": raw_lines
        }

    def _format_structured_markdown(self, lines: List[str]) -> str:
        """
        Applies heuristic layout, heading, list, and mathematical formula
        formatting to raw OCR text lines.
        """
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Detect Major Chapter & Section Headings
            if re.match(r"^(?:CHAPTER|MODULE|UNIT|SECTION)\s+[A-Z0-9]+", line, re.IGNORECASE):
                cleaned_lines.append(f"\n# {line}\n")
            elif re.match(r"^[0-9]+\.[0-9]+\s+[A-Z]", line):
                cleaned_lines.append(f"\n## {line}\n")
            elif re.match(r"^[0-9]+\.[0-9]+\.[0-9]+\s+[A-Z]", line):
                cleaned_lines.append(f"\n### {line}\n")
            elif re.match(r"^(?:Figure|Table)\s+[0-9]+", line, re.IGNORECASE):
                cleaned_lines.append(f"\n**{line}**\n")
            # Detect List Items (i., ii., 1., a.)
            elif re.match(r"^(?:[ivx]+\.|\([ivx]+\)|[0-9]+\.|\([0-9]+\)|[a-z]\.|\([a-z]\))\s+", line, re.IGNORECASE):
                cleaned_lines.append(f"- {line}")
            # Format Mathematical formulas / equations with LaTeX markers
            elif any(sym in line for sym in ["=", "∑", "√", "±", "×", "÷", "≤", "≥", "≠", "→", "Δ", "λ", "μ", "σ"]):
                # Clean mathematical spacing and wrap in block LaTeX notation
                math_line = line.replace("∑", "\\sum ").replace("√", "\\sqrt").replace("±", "\\pm ")
                cleaned_lines.append(f"\n$$\n{math_line}\n$$\n")
            else:
                cleaned_lines.append(line)

        return "\n".join(cleaned_lines)
