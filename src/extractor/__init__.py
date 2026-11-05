"""
KITCOEK RAG Agent — Phase C Extraction modules.

Modules:
- html_extractor  : Trafilatura + BeautifulSoup HTML extraction
- pdf_extractor   : PyMuPDF page-level PDF extraction (OCR optional)
- office_extractor: DOCX, PPTX, XLSX, CSV extraction
- quality_checks  : Automated extraction quality reporting
"""

from .html_extractor  import HTMLExtractor
from .pdf_extractor   import PDFExtractor, extract_pdf_to_json
from .office_extractor import extract_document
from .quality_checks  import QualityChecker

__all__ = [
    "HTMLExtractor",
    "PDFExtractor",
    "extract_pdf_to_json",
    "extract_document",
    "QualityChecker",
]
