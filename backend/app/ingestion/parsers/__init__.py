"""Block-typed parsers.

Each parser returns a list of Block dataclasses with a `kind` field
(table/paragraph/list) plus source metadata (page_no, section_path).
Structural type is preserved so the chunker can apply the right rule.
"""

from dataclasses import dataclass, field


@dataclass
class Block:
    kind: str  # "table" | "paragraph" | "list"
    text: str  # for tables: markdown-serialized; for lists: header+items joined
    rows: list[list[str]] | None = None  # tables only, header at [0]
    items: list[str] | None = None  # lists only
    header: str | None = None  # list header
    page_no: int | None = None
    section_path: str | None = None
    extra: dict = field(default_factory=dict)
