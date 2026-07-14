"""Type-specific chunking.

- Tables: header row + N data rows per chunk. Small tables (<= threshold rows) kept whole.
- Paragraphs: recursive-character splitter, targeting token budget.
- Lists: header + K items per chunk. Small lists kept whole.

Every child chunk carries a `parent_id` back to its full source block.
"""

import re
import uuid
from dataclasses import dataclass

from app.config import settings
from app.ingestion.parsers import Block
from app.ingestion.parsers.pdf import _table_to_markdown


@dataclass
class Chunk:
    parent_id: str
    parent_text: str
    text: str  # what gets embedded (already PII-masked upstream)
    component_type: str
    chunk_index: int
    page_no: int | None
    section_path: str | None


def chunk_block(b: Block) -> tuple[str, list[Chunk]]:
    """Returns (parent_id, list of child chunks)."""
    parent_id = str(uuid.uuid4())
    parent_text = b.text

    if b.kind == "table":
        children = _chunk_table(parent_id, parent_text, b)
    elif b.kind == "list":
        children = _chunk_list(parent_id, parent_text, b)
    else:
        children = _chunk_paragraph(parent_id, parent_text, b)
    return parent_id, children


def _chunk_table(pid: str, ptext: str, b: Block) -> list[Chunk]:
    rows = b.rows or []
    if len(rows) <= settings.table_small_threshold + 1:  # +1 for header
        return [
            Chunk(pid, ptext, ptext, "table", 0, b.page_no, b.section_path),
        ]
    header, data = rows[0], rows[1:]
    step = settings.table_rows_per_chunk
    children: list[Chunk] = []
    for i in range(0, len(data), step):
        window = [header] + data[i : i + step]
        text = _table_to_markdown(window)
        children.append(Chunk(pid, ptext, text, "table", len(children), b.page_no, b.section_path))
    return children


def _chunk_list(pid: str, ptext: str, b: Block) -> list[Chunk]:
    header = b.header or "List"
    items = b.items or []
    if len(items) <= settings.list_items_per_chunk:
        return [Chunk(pid, ptext, ptext, "list", 0, b.page_no, b.section_path)]
    step = settings.list_items_per_chunk
    children: list[Chunk] = []
    for i in range(0, len(items), step):
        window = items[i : i + step]
        text = header + "\n" + "\n".join(f"- {it}" for it in window)
        children.append(Chunk(pid, ptext, text, "list", len(children), b.page_no, b.section_path))
    return children


_TOKEN_RE = re.compile(r"\S+")


def _tok_len(s: str) -> int:
    # Cheap whitespace approximation — good enough for chunk sizing without loading a tokenizer.
    return len(_TOKEN_RE.findall(s))


def _chunk_paragraph(pid: str, ptext: str, b: Block) -> list[Chunk]:
    target = settings.para_chunk_tokens
    overlap = settings.para_chunk_overlap
    if _tok_len(ptext) <= target:
        return [Chunk(pid, ptext, ptext, "paragraph", 0, b.page_no, b.section_path)]

    # Split by sentences, then greedily pack up to `target` tokens with `overlap` carry-over.
    sentences = re.split(r"(?<=[.!?])\s+", ptext)
    children: list[Chunk] = []
    buf: list[str] = []
    buf_tok = 0
    for s in sentences:
        n = _tok_len(s)
        if buf_tok + n > target and buf:
            text = " ".join(buf).strip()
            children.append(Chunk(pid, ptext, text, "paragraph", len(children), b.page_no, b.section_path))
            # Carry overlap-worth of trailing sentences into the next window.
            carry: list[str] = []
            ctok = 0
            for prev in reversed(buf):
                carry.insert(0, prev)
                ctok += _tok_len(prev)
                if ctok >= overlap:
                    break
            buf, buf_tok = carry[:], ctok
        buf.append(s)
        buf_tok += n
    if buf:
        text = " ".join(buf).strip()
        children.append(Chunk(pid, ptext, text, "paragraph", len(children), b.page_no, b.section_path))
    return children
