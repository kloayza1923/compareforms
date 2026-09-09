"""Extension seam only: B is deliberately not a loaded/trained model."""
from pathlib import Path
from typing import Protocol

class ComparisonStrategy(Protocol):
    def compare(self, original: Path, modified: Path, *, ocr_enabled: bool) -> dict: ...

class MinimumErrorStrategy:
    def compare(self, original, modified, *, ocr_enabled=True):
        from .comparison import compare_documents
        return compare_documents(original, modified, ocr_enabled=ocr_enabled)

class EncoderDecoderStrategy:
    evaluation_pdf_threshold = 1000
    def compare(self, original, modified, *, ocr_enabled=True):
        raise NotImplementedError("B encoder-decoder reservado. Superar 1000 PDF no autoriza entrenamiento ni inferencia automática.")
