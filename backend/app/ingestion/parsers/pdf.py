"""PDF parser using pdfplumber for text + tables.

For a prototype we rely on pdfplumber only (camelot adds Ghostscript
brittleness). Text blocks are grouped by page and split into paragraph
blocks on double newlines; tables are extracted structurally.
"""

import io
import re

import pdfplumber

from app.ingestion.parsers import Block


def parse_pdf(data: bytes) -> list[Block]:
    blocks: list[Block] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            # Extract tables first, then remove their bounding boxes from text.
            for tbl in page.extract_tables() or []:
                rows = [[(c or "").strip() for c in row] for row in tbl if any(row)]
                if not rows:
                    continue
                blocks.append(
                    Block(
                        kind="table",
                        text=_table_to_markdown(rows),
                        rows=rows,
                        page_no=page_no,
                    )
                )
            text = page.extract_text() or ""
            for para in _split_paragraphs(text):
                if _looks_like_list(para):
                    header, items = _parse_list(para)
                    blocks.append(
                        Block(
                            kind="list",
                            text=header + "\n" + "\n".join(f"- {it}" for it in items),
                            header=header,
                            items=items,
                            page_no=page_no,
                        )
                    )
                elif para.strip():
                    blocks.append(Block(kind="paragraph", text=para.strip(), page_no=page_no))
    return blocks


def _split_paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


_LIST_LINE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def _looks_like_list(text: str) -> bool:
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 3:
        return False
    listy = sum(1 for l in lines if _LIST_LINE.match(l))
    return listy >= max(2, len(lines) // 2)


def _parse_list(text: str) -> tuple[str, list[str]]:
    lines = [l for l in text.splitlines() if l.strip()]
    header_lines, items = [], []
    for l in lines:
        if _LIST_LINE.match(l):
            items.append(_LIST_LINE.sub("", l).strip())
        elif not items:
            header_lines.append(l.strip())
    header = " ".join(header_lines) or "List"
    return header, items


def _table_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header, *rest = rows
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    for r in rest:
        # pad row to header length
        r = r + [""] * (len(header) - len(r))
        out.append("| " + " | ".join(r[: len(header)]) + " |")
    return "\n".join(out)
