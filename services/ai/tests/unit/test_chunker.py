from trustdesk_ai.ingestion.chunker import ChunkConfig, chunk_blocks, embedding_text, split_sentences
from trustdesk_ai.ingestion.hashing import content_hash
from trustdesk_ai.ingestion.tokens import count_tokens
from trustdesk_ai.ingestion.types import Block

CFG = ChunkConfig(target_tokens=500, max_tokens=600, overlap_ratio=0.15)


def para(n: int, word: str = "service") -> Block:
    return Block("paragraph", " ".join(f"Our {word} sentence number {i} is here." for i in range(n)))


def test_heading_path_and_section_preserved():
    blocks = [
        Block("heading", "Services", level=1),
        Block("heading", "Web design", level=2),
        Block("paragraph", "We design websites."),
        Block("heading", "Pricing", level=1),
        Block("paragraph", "Prices are on request."),
    ]
    chunks = chunk_blocks(blocks, CFG)
    assert [c.heading_path for c in chunks] == [("Services", "Web design"), ("Pricing",)]
    assert chunks[0].section == "Web design"
    assert chunks[0].parent_section_id == "services"
    assert chunks[1].parent_section_id is None
    assert [c.ordinal for c in chunks] == [0, 1]


def test_chunks_respect_max_tokens_and_overlap_within_section():
    chunks = chunk_blocks([Block("heading", "About", level=1), *[para(12) for _ in range(10)]], CFG)
    assert len(chunks) > 1
    assert all(c.token_count <= CFG.max_tokens for c in chunks)
    # overlap: the second chunk starts with text that ended the first chunk
    first_last_sentence = split_sentences(chunks[0].content)[-1]
    assert chunks[1].content.startswith(first_last_sentence) or first_last_sentence in chunks[1].content[:600]


def test_no_overlap_across_sections():
    blocks = [Block("heading", "A", level=1), para(80, "alpha"), Block("heading", "B", level=1), para(3, "beta")]
    chunks = chunk_blocks(blocks, CFG)
    b = [c for c in chunks if c.section == "B"]
    assert b and "alpha" not in b[0].content


def test_table_is_atomic_when_it_fits():
    table = "| Plan | Price |\n|---|---|\n| Basic | documented |\n| Pro | documented |"
    chunks = chunk_blocks([Block("paragraph", "Intro."), Block("table", table)], CFG)
    assert len(chunks) == 1 and table in chunks[0].content


def test_oversized_table_repeats_header_in_every_piece():
    header = "| Item | Detail |\n|---|---|"
    rows = "\n".join(f"| item {i} | detail text for row number {i} with words |" for i in range(200))
    chunks = chunk_blocks([Block("table", f"{header}\n{rows}")], CFG)
    assert len(chunks) > 1
    assert all(c.content.lstrip().startswith("| Item | Detail |") or header in c.content for c in chunks)
    assert all(c.token_count <= CFG.max_tokens for c in chunks)


def test_urdu_sentences_split_on_urdu_full_stop():
    assert split_sentences("یہ پہلا جملہ ہے۔ یہ دوسرا جملہ ہے؟ تیسرا") == [
        "یہ پہلا جملہ ہے۔",
        "یہ دوسرا جملہ ہے؟",
        "تیسرا",
    ]


def test_page_number_and_hash():
    chunks = chunk_blocks([Block("paragraph", "Page two text.", page_number=2)], CFG)
    assert chunks[0].page_number == 2
    assert chunks[0].content_hash == content_hash("Page two text.")


def test_giant_sentence_is_hard_split():
    chunks = chunk_blocks([Block("paragraph", " ".join(["word"] * 3000))], CFG)
    assert len(chunks) > 1 and all(c.token_count <= CFG.max_tokens for c in chunks)


def test_empty_input():
    assert chunk_blocks([], CFG) == []


def test_embedding_text_includes_context():
    assert embedding_text("Acme", ["Services", "Web"], "body") == "Acme > Services > Web\n\nbody"
    assert embedding_text(None, [], "body") == "body"


def test_config_validation():
    import pytest

    with pytest.raises(ValueError):
        ChunkConfig(target_tokens=700, max_tokens=600)


def test_count_tokens_nonzero():
    assert count_tokens("hello world") > 0
