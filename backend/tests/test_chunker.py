from app.config import settings
from app.ingestion.chunker import chunk_block
from app.ingestion.parsers import Block


def test_small_table_kept_whole():
    rows = [["Name", "Age"], ["Alice", "30"], ["Bob", "25"]]
    b = Block(kind="table", text="| Name | Age |", rows=rows)
    pid, children = chunk_block(b)
    assert len(children) == 1
    assert children[0].component_type == "table"


def test_large_table_windowed():
    rows = [["h1", "h2"]] + [[f"a{i}", f"b{i}"] for i in range(30)]
    b = Block(kind="table", text="ignored", rows=rows)
    pid, children = chunk_block(b)
    # 30 rows / 3 per chunk = 10 windows
    assert len(children) == 10
    assert all(c.component_type == "table" for c in children)


def test_small_list_kept_whole():
    items = ["a", "b", "c"]
    b = Block(kind="list", text="H\n- a\n- b\n- c", header="H", items=items)
    pid, children = chunk_block(b)
    assert len(children) == 1


def test_large_list_windowed():
    items = [f"item{i}" for i in range(20)]
    b = Block(kind="list", text="H", header="H", items=items)
    pid, children = chunk_block(b)
    assert len(children) == 5  # 20/4


def test_short_paragraph_kept_whole():
    b = Block(kind="paragraph", text="Short paragraph text.")
    pid, children = chunk_block(b)
    assert len(children) == 1


def test_long_paragraph_split_with_overlap():
    # Build a paragraph well over the token budget with many sentences.
    sentences = ["This is sentence number %d word word word word." % i for i in range(200)]
    b = Block(kind="paragraph", text=" ".join(sentences))
    pid, children = chunk_block(b)
    assert len(children) > 1
    # Every child should reference the same parent id.
    assert len({c.parent_id for c in children}) == 1
