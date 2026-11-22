from app.config import Settings
from app.indexing.chunker import Chunk, chunk_page, estimate_tokens

SETTINGS = Settings(_env_file=None)


def words(n: int, word: str = "word") -> str:
    return " ".join(f"{word}{i}" for i in range(n))


def test_empty_text_gives_no_chunks() -> None:
    assert chunk_page("   \n", SETTINGS) == []


def test_small_page_is_one_chunk_with_common_heading_path() -> None:
    text = "# Returns\n\nIntro.\n\n## Window\n\nThirty days.\n\n## Labels\n\nPrepaid."
    assert chunk_page(text, SETTINGS) == [Chunk(heading_path="Returns", text=text)]


def test_heading_path_follows_nesting() -> None:
    big = words(450)
    text = f"# Returns\n\n## Window\n\n{big}\n\n## Labels\n\n### Printing\n\n{big}"
    paths = [chunk.heading_path for chunk in chunk_page(text, SETTINGS)]
    assert paths[0] == "Returns > Window"
    assert paths[-1] == "Returns > Labels > Printing"


def test_sections_are_packed_up_to_target() -> None:
    section = words(120)
    text = "\n\n".join(f"## Topic {i}\n\n{section}" for i in range(8))
    chunks = chunk_page(text, SETTINGS)
    assert 1 < len(chunks) < 8
    assert all(estimate_tokens(c.text) <= SETTINGS.chunk_max_tokens for c in chunks)
    assert "## Topic 0" in chunks[0].text


def test_oversized_section_is_split_with_overlap() -> None:
    text = "# Policy\n\n" + words(2500)
    chunks = chunk_page(text, SETTINGS)
    assert len(chunks) > 1
    assert all(estimate_tokens(c.text) <= SETTINGS.chunk_max_tokens for c in chunks)
    assert all(c.heading_path == "Policy" for c in chunks)
    first_words = chunks[0].text.split()
    second_words = chunks[1].text.split()
    assert " ".join(second_words[:5]) in " ".join(first_words[-40:]), "starts with previous tail"


def test_long_paragraphs_are_split_on_paragraph_boundaries_first() -> None:
    paragraphs = [words(300, f"p{i}x") for i in range(4)]
    text = "# Guide\n\n" + "\n\n".join(paragraphs)
    chunks = chunk_page(text, SETTINGS)
    assert all(estimate_tokens(c.text) <= SETTINGS.chunk_max_tokens for c in chunks)
    joined = " ".join(c.text for c in chunks)
    assert all(p.split()[0] in joined and p.split()[-1] in joined for p in paragraphs)


def test_text_without_headings_has_empty_path() -> None:
    chunks = chunk_page("Just some help text without any headings at all.", SETTINGS)
    assert chunks == [
        Chunk(heading_path="", text="Just some help text without any headings at all.")
    ]


def test_text_before_first_heading_is_kept() -> None:
    text = "Welcome to support.\n\n# Shipping\n\nShips in two days."
    chunks = chunk_page(text, SETTINGS)
    assert "Welcome to support." in chunks[0].text
    assert chunks[0].heading_path == ""


def test_estimate_tokens_is_about_four_chars_per_token() -> None:
    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens("") == 0


def test_tiny_trailing_section_merges_into_previous_chunk() -> None:
    settings = Settings(_env_file=None, chunk_target_tokens=450)
    n = next(
        n for n in range(100, 400) if estimate_tokens(f"# Guide\n\n## Long\n\n{words(n)}") > 446
    )
    text = f"# Guide\n\n## Long\n\n{words(n)}\n\n## Tiny\n\nOne short closing line."
    assert estimate_tokens(text) > settings.chunk_target_tokens
    chunks = chunk_page(text, settings)
    assert len(chunks) == 1
    assert chunks[0].heading_path == "Guide"
