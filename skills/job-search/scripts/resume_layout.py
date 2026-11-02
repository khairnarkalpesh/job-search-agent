"""Read a resume file the way a plain resume parser would, and note what such a parser misses.

Only the file's structure is inspected here: tables, text boxes, columns, page headers,
images and hidden text. What any of it means for a score is decided in ats_readiness.py.
Text found in headers, text boxes or hidden runs is kept in memory for those checks and
never written anywhere.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from resume_parser import MINIMUM_RESUME_TEXT_LENGTH, ResumeParseError, extract_resume_text

# Two-column PDFs come out of layout extraction as lines with a wide gap in the middle.
# Right-aligned dates do too, but only on a job's heading line, so a share is required.
_COLUMN_GAP = re.compile(r"\S {6,}\S")
_MINIMUM_LINES_FOR_COLUMN_CHECK = 8
_COLUMN_LINE_SHARE = 0.4
_SMALLEST_VISIBLE_HALF_POINTS = 8  # 4pt
_WHITE = {"FFFFFF", "FFFFFE", "FEFEFE"}
_IMAGE_ONLY_PAGE_TEXT = 50


@dataclass
class LayoutFindings:
    kind: str  # pdf, docx or text
    pages: int | None = None
    tables: int = 0
    table_text_share: float = 0.0
    columns: int = 1
    columns_inferred: bool = False  # a guess from PDF text positions, not a declared layout
    text_box_text: str = ""
    header_footer_text: str = ""
    images: int = 0
    image_only_pages: int = 0
    hidden_text: str = ""
    markdown_tables: int = 0


@dataclass
class ResumeDocument:
    name: str
    text: str  # what a plain parser extracts
    layout: LayoutFindings = field(default_factory=lambda: LayoutFindings("text"))

    @property
    def text_outside_body(self) -> str:
        """Text that exists in the file but a plain parser may not read."""
        return "\n".join(part for part in (self.layout.header_footer_text, self.layout.text_box_text) if part)


def inspect_resume(path: str | Path) -> ResumeDocument:
    """Raises ResumeParseError for a missing, unsupported, unreadable or empty file."""
    resume_path = Path(path)
    text = extract_resume_text(resume_path)
    suffix = resume_path.suffix.lower()
    if suffix == ".docx":
        layout = _docx_layout(resume_path, text)
    elif suffix == ".pdf":
        layout = _pdf_layout(resume_path)
    else:
        layout = LayoutFindings("text", markdown_tables=len(re.findall(r"^\s*\|?\s*:?-{3,}", text, re.MULTILINE)))
    document = ResumeDocument(resume_path.name, text, layout)
    if len(text.strip()) < MINIMUM_RESUME_TEXT_LENGTH and len(document.text_outside_body.strip()) < MINIMUM_RESUME_TEXT_LENGTH:
        raise ResumeParseError(f"{resume_path.name} has almost no extractable text. "
                               "If it is a scanned PDF, provide a text-based PDF, DOCX, TXT or Markdown copy.")
    return document


def _xml_text(element) -> str:
    from docx.oxml.ns import qn
    return "".join(node.text or "" for node in element.iter(qn("w:t")))


def _docx_layout(path: Path, body_text: str) -> LayoutFindings:
    from docx import Document
    from docx.opc.exceptions import PackageNotFoundError
    from docx.oxml.ns import qn
    try:
        document = Document(str(path))
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError) as error:
        raise ResumeParseError(f"Could not read {path.name}: {error}") from error
    body = document.element.body
    table_text = sum(len(_xml_text(table._tbl)) for table in document.tables)
    columns = [int(cols.get(qn("w:num")) or 1) for cols in body.iter(qn("w:cols"))]
    return LayoutFindings(
        "docx",
        tables=len(document.tables),
        table_text_share=round(table_text / max(len(body_text), 1), 2),
        columns=max(columns, default=1),
        text_box_text="\n".join(_xml_text(box) for box in body.iter(qn("w:txbxContent"))).strip(),
        header_footer_text=_docx_header_footer_text(document),
        images=sum(1 for _ in body.iter(qn("a:blip"))),
        hidden_text=" ".join(_xml_text(run) for run in body.iter(qn("w:r")) if _is_hidden_run(run)).strip(),
    )


def _docx_header_footer_text(document) -> str:
    parts = []
    for section in document.sections:
        for part in (section.header, section.footer, section.first_page_header, section.first_page_footer):
            if not part.is_linked_to_previous:
                parts.append(_xml_text(part._element))
    return "\n".join(part.strip() for part in parts if part.strip())


def _is_hidden_run(run) -> bool:
    """Text set to vanish, white, or under 4pt: invisible to a reader, visible to a parser."""
    from docx.oxml.ns import qn
    properties = run.find(qn("w:rPr"))
    if properties is None:
        return False
    vanish = properties.find(qn("w:vanish"))
    if vanish is not None and vanish.get(qn("w:val"), "true") not in ("0", "false"):
        return True
    color = properties.find(qn("w:color"))
    if color is not None and (color.get(qn("w:val")) or "").upper() in _WHITE:
        return True
    size = properties.find(qn("w:sz"))
    return size is not None and (size.get(qn("w:val")) or "").isdigit() and int(size.get(qn("w:val"))) < _SMALLEST_VISIBLE_HALF_POINTS


def _pdf_layout(path: Path) -> LayoutFindings:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError
    try:
        reader = PdfReader(str(path))
        pages = list(reader.pages)
        layout_lines = [line for page in pages for line in page.extract_text(extraction_mode="layout").splitlines()
                        if line.strip()]
        page_texts = [page.extract_text() or "" for page in pages]
    except (PyPdfError, OSError, ValueError) as error:
        raise ResumeParseError(f"Could not read {path.name}: {error}") from error
    images_per_page = [_pdf_image_count(page) for page in pages]
    gap_lines = sum(1 for line in layout_lines if _COLUMN_GAP.search(line.strip()))
    two_columns = len(layout_lines) >= _MINIMUM_LINES_FOR_COLUMN_CHECK and gap_lines / len(layout_lines) >= _COLUMN_LINE_SHARE
    return LayoutFindings(
        "pdf",
        pages=len(pages),
        columns=2 if two_columns else 1,
        columns_inferred=two_columns,
        images=sum(images_per_page),
        image_only_pages=sum(1 for text, images in zip(page_texts, images_per_page, strict=True)
                             if images and len(text.strip()) < _IMAGE_ONLY_PAGE_TEXT),
    )


def _pdf_image_count(page) -> int:
    resources = page.get("/Resources")
    xobjects = resources.get_object().get("/XObject") if resources else None
    if not xobjects:
        return 0
    return sum(1 for item in xobjects.get_object().values() if item.get_object().get("/Subtype") == "/Image")
