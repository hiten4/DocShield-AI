"""Component-type classification.

Parsers already produce typed Blocks (table/paragraph/list) because they
have structural signals we shouldn't discard. This module is a
verification pass for edge cases where a parser mislabels — e.g., a
paragraph that's actually a bulleted list.
"""

import re

from app.ingestion.parsers import Block
from app.ingestion.parsers.pdf import _looks_like_list, _parse_list


def refine_component(b: Block) -> Block:
    if b.kind == "paragraph" and _looks_like_list(b.text):
        header, items = _parse_list(b.text)
        return Block(
            kind="list",
            text=header + "\n" + "\n".join(f"- {it}" for it in items),
            header=header,
            items=items,
            page_no=b.page_no,
            section_path=b.section_path,
        )
    return b
