Write a Python module that splits a Markdown document into chunks for a language model, and checks
that a value the model quotes really appears near the line it cites.

## Lines, headings and fences

- The document's lines are `text.splitlines()`, numbered from 1.
- A **fence** opens on a line whose text, after removing leading spaces, starts with three backticks or
  three tildes, and closes on the next line that, after removing leading spaces, starts with the same
  three characters. The opening line, the closing line and everything between belong to the fenced
  block. A fence that never closes runs to the end of the document.
- A **heading** is a line outside any fenced block that matches `#` repeated 1 to 6 times, then at least
  one space or tab, then the title. The level is the number of `#`. The title is the rest of the line
  with surrounding whitespace removed, and with any trailing run of `#` characters that is preceded by
  whitespace (or makes up the whole remaining text) removed, then stripped again. So `## Setup ##` has
  the title `Setup`, `# C#` has the title `C#`, and `#Title` is not a heading.
- The **heading path** of a line is the list of titles of the headings that contain it, outermost first.
  Walking down the document, a heading of level L removes every open heading of level L or deeper and is
  then added. A heading line belongs to its own section, so its path ends with its own title. Lines
  before the first heading have an empty path.

## API

- `outline(text) -> list[tuple[int, int, str]]`: every heading as `(line_number, level, title)`, in order.
- `heading_path(text, line) -> list[str]`: the heading path of line number `line`. A line number
  outside 1..number of lines raises `ValueError`.
- `split(text, max_lines) -> list[Chunk]`. `max_lines` below 1 raises `ValueError`. First the document
  is divided into **blocks**: each fenced block is one block, and every other line is a block of its own.
  Then the blocks are taken in order and added to the current chunk. Before adding a block, the current
  chunk is closed and a new one started if the chunk is not empty and either adding the block would make
  it longer than `max_lines` lines, or the block is a heading of level 1 or 2. A fenced block longer than
  `max_lines` therefore gets a chunk of its own, longer than `max_lines`. An empty document gives `[]`.
- `Chunk` has the attributes `start` and `end` (first and last line numbers, inclusive), `lines` (the
  list of line texts) and `headings` (the heading path of line `start`). Two chunks are equal when all
  four attributes are equal.
- `check_citation(text, line, value, window=2) -> bool`. Both the value and each line are
  **normalised**: every `**`, `__` and backtick removed, runs of whitespace replaced by one space, and the
  result stripped. Comparison is case-sensitive. Return `True` when the normalised value is not empty
  and either it is a substring of a normalised line whose number is within `window` of `line` (lines
  outside the document are ignored), or it equals the normalised title of one of the headings in the
  heading path of `line`. A `line` outside the document returns `False`.
