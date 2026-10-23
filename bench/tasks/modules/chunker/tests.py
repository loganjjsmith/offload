from solution import Chunk, check_citation, heading_path, outline, split

DOC = """Intro line
# Guide
Some text
## Setup ##
Install it.
```bash
# not a heading
pip install thing
```
### Details
More **bold** text.
## Usage
Run `tool --go` now.
# Appendix
End."""


def test_outline():
    assert outline(DOC) == [(2, 1, "Guide"), (4, 2, "Setup"), (10, 3, "Details"), (12, 2, "Usage"),
                            (14, 1, "Appendix")]


def test_outline_heading_rules():
    text = "#NoSpace\n# C#\n####### seven\n#\tTabbed\n  # indented\n###### Six ###\n# Ends # here"
    assert outline(text) == [(2, 1, "C#"), (4, 1, "Tabbed"), (6, 6, "Six"), (7, 1, "Ends # here")]


def test_outline_skips_fences():
    text = "~~~\n# inside tilde\n~~~\n```\n# inside backtick\n```\n# real"
    assert outline(text) == [(7, 1, "real")]


def test_unclosed_fence_runs_to_end():
    text = "# A\n```\n# B\n# C"
    assert outline(text) == [(1, 1, "A")]


def test_indented_fence():
    text = "  ```\n# hidden\n   ```\n# shown"
    assert outline(text) == [(4, 1, "shown")]


def test_tilde_does_not_close_backtick_fence():
    text = "```\n~~~\n# hidden\n```\n# shown"
    assert outline(text) == [(5, 1, "shown")]


def test_heading_path_basic():
    assert heading_path(DOC, 1) == []
    assert heading_path(DOC, 2) == ["Guide"]
    assert heading_path(DOC, 5) == ["Guide", "Setup"]
    assert heading_path(DOC, 7) == ["Guide", "Setup"]
    assert heading_path(DOC, 11) == ["Guide", "Setup", "Details"]
    assert heading_path(DOC, 13) == ["Guide", "Usage"]
    assert heading_path(DOC, 15) == ["Appendix"]


def test_heading_path_skipped_levels():
    text = "# A\n### C\nx\n## B\ny"
    assert heading_path(text, 3) == ["A", "C"]
    assert heading_path(text, 5) == ["A", "B"]


def test_heading_path_out_of_range():
    for bad in (0, 16, -1):
        try:
            heading_path(DOC, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"line {bad} accepted")


def test_split_validates_max_lines():
    try:
        split(DOC, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("max_lines 0 accepted")


def test_split_empty():
    assert split("", 5) == []


def test_split_covers_every_line_once():
    for size in (1, 2, 3, 5, 8, 100):
        chunks = split(DOC, size)
        numbers = [n for c in chunks for n in range(c.start, c.end + 1)]
        assert numbers == list(range(1, 16)), size
        for c in chunks:
            assert c.lines == DOC.splitlines()[c.start - 1:c.end]


def test_split_large_window_breaks_at_level_two_headings():
    chunks = split(DOC, 100)
    assert [(c.start, c.end) for c in chunks] == [(1, 1), (2, 3), (4, 11), (12, 13), (14, 15)]


def test_split_keeps_fence_whole():
    chunks = split(DOC, 3)
    assert [(c.start, c.end) for c in chunks] == [(1, 1), (2, 3), (4, 5), (6, 9), (10, 11), (12, 13), (14, 15)]


def test_split_fence_longer_than_max_gets_own_chunk():
    chunks = split(DOC, 2)
    assert [(c.start, c.end) for c in chunks] == [(1, 1), (2, 3), (4, 5), (6, 9), (10, 11), (12, 13), (14, 15)]
    assert chunks[3].lines == ["```bash", "# not a heading", "pip install thing", "```"]


def test_split_level_three_heading_does_not_break():
    text = "# A\none\n### B\ntwo"
    assert [(c.start, c.end) for c in split(text, 10)] == [(1, 4)]


def test_split_max_one():
    text = "a\nb\nc"
    assert [(c.start, c.end) for c in split(text, 1)] == [(1, 1), (2, 2), (3, 3)]


def test_split_plain_text_fills_chunks():
    text = "\n".join(f"line {i}" for i in range(1, 11))
    assert [(c.start, c.end) for c in split(text, 4)] == [(1, 4), (5, 8), (9, 10)]


def test_split_headings_attribute():
    chunks = split(DOC, 3)
    assert [c.headings for c in chunks] == [[], ["Guide"], ["Guide", "Setup"], ["Guide", "Setup"],
                                            ["Guide", "Setup", "Details"], ["Guide", "Usage"], ["Appendix"]]


def test_chunk_equality():
    assert split("# A\nx", 5) == [Chunk(1, 2, ["# A", "x"], ["A"])]


def test_citation_exact_line():
    assert check_citation(DOC, 5, "Install it.")


def test_citation_within_window():
    assert check_citation(DOC, 7, "Install it.")
    assert not check_citation(DOC, 8, "Install it.")
    assert check_citation(DOC, 8, "Install it.", window=3)


def test_citation_ignores_markup():
    assert check_citation(DOC, 11, "More bold text.")
    assert check_citation(DOC, 13, "tool --go")
    assert check_citation(DOC, 11, "**More** bold")


def test_citation_collapses_whitespace():
    text = "alpha   beta\tgamma"
    assert check_citation(text, 1, "alpha beta  gamma")


def test_citation_case_sensitive():
    assert not check_citation(DOC, 5, "install it.")


def test_citation_heading_title():
    assert check_citation(DOC, 13, "Guide", window=0)
    assert check_citation(DOC, 11, "Setup", window=0)
    assert not check_citation(DOC, 15, "Guide", window=0)


def test_citation_heading_must_match_whole_title():
    assert not check_citation(DOC, 13, "Gui", window=0)


def test_citation_line_outside_document():
    assert not check_citation(DOC, 0, "Intro")
    assert not check_citation(DOC, 99, "End.")


def test_citation_window_clipped_at_edges():
    assert check_citation(DOC, 1, "Guide", window=1)
    assert check_citation(DOC, 15, "Appendix", window=1)


def test_citation_empty_value():
    assert not check_citation(DOC, 5, "")
    assert not check_citation(DOC, 5, "  ** ")
