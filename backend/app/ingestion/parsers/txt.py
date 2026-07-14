import re

from app.ingestion.parsers import Block
from app.ingestion.parsers.pdf import _looks_like_list, _parse_list


def parse_txt(data: bytes) -> list[Block]:
    text = data.decode("utf-8", errors="replace")
    blocks: list[Block] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if _looks_like_list(para):
            header, items = _parse_list(para)
            blocks.append(
                Block(
                    kind="list",
                    text=header + "\n" + "\n".join(f"- {it}" for it in items),
                    header=header,
                    items=items,
                )
            )
        else:
            blocks.append(Block(kind="paragraph", text=para))
    return blocks
