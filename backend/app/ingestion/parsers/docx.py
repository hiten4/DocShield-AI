import io

from docx import Document as _Docx

from app.ingestion.parsers import Block


def parse_docx(data: bytes) -> list[Block]:
    doc = _Docx(io.BytesIO(data))
    blocks: list[Block] = []
    section_path = None

    # Tables (extracted separately to preserve structure)
    for tbl in doc.tables:
        rows = [[c.text.strip() for c in row.cells] for row in tbl.rows]
        rows = [r for r in rows if any(r)]
        if rows:
            blocks.append(Block(kind="table", text=_md(rows), rows=rows, section_path=section_path))

    # Paragraphs / lists (list-style paragraphs share a numPr — treat consecutive as one list)
    buffer: list[str] = []
    header = None
    for p in doc.paragraphs:
        style = (p.style.name or "").lower()
        is_heading = style.startswith("heading")
        is_list = "list" in style or (p._p.pPr is not None and p._p.pPr.numPr is not None)
        text = p.text.strip()
        if not text:
            _flush_list(blocks, buffer, header, section_path)
            buffer, header = [], None
            continue
        if is_heading:
            _flush_list(blocks, buffer, header, section_path)
            buffer, header = [], None
            section_path = text
            continue
        if is_list:
            if not buffer:
                header = section_path or "List"
            buffer.append(text)
        else:
            _flush_list(blocks, buffer, header, section_path)
            buffer, header = [], None
            blocks.append(Block(kind="paragraph", text=text, section_path=section_path))
    _flush_list(blocks, buffer, header, section_path)
    return blocks


def _flush_list(blocks, items, header, section_path):
    if items:
        h = header or "List"
        blocks.append(
            Block(
                kind="list",
                text=h + "\n" + "\n".join(f"- {it}" for it in items),
                header=h,
                items=list(items),
                section_path=section_path,
            )
        )


def _md(rows):
    from app.ingestion.parsers.pdf import _table_to_markdown
    return _table_to_markdown(rows)
