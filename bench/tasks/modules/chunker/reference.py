import re
from dataclasses import dataclass, field

HEADING = re.compile(r"^(#{1,6})[ \t]+(.*)$")


@dataclass
class Chunk:
    start: int
    end: int
    lines: list = field(default_factory=list)
    headings: list = field(default_factory=list)


def _title(rest):
    rest = rest.strip()
    m = re.search(r"(^|\s)#+$", rest)
    if m:
        rest = rest[:m.start()]
    return rest.strip()


def _scan(text):
    """Per line: (fence block id or None, heading (level, title) or None)."""
    lines = text.splitlines()
    info, fence, block = [], None, 0
    for line in lines:
        lead = line.lstrip(" ")
        if fence is None and lead[:3] in ("```", "~~~"):
            fence, block = lead[:3], block + 1
            info.append((block, None))
            continue
        if fence is not None:
            info.append((block, None))
            if lead.startswith(fence):
                fence = None
            continue
        m = HEADING.match(line)
        info.append((None, (len(m.group(1)), _title(m.group(2))) if m else None))
    return lines, info


def _paths(info):
    stack, out = [], []
    for _, heading in info:
        if heading:
            level, title = heading
            stack = [(lv, t) for lv, t in stack if lv < level] + [(level, title)]
        out.append([t for _, t in stack])
    return out


def outline(text):
    _, info = _scan(text)
    return [(i + 1, h[0], h[1]) for i, (_, h) in enumerate(info) if h]


def heading_path(text, line):
    lines, info = _scan(text)
    if not 1 <= line <= len(lines):
        raise ValueError(f"line {line} is outside the document")
    return _paths(info)[line - 1]


def split(text, max_lines):
    if max_lines < 1:
        raise ValueError("max_lines must be at least 1")
    lines, info = _scan(text)
    paths = _paths(info)
    blocks, i = [], 0
    while i < len(lines):
        j = i + 1
        if info[i][0] is not None:
            while j < len(lines) and info[j][0] == info[i][0]:
                j += 1
        blocks.append((i, j))
        i = j
    chunks, current = [], None
    for a, b in blocks:
        heading = info[a][1]
        if current is not None and (current[1] - current[0] + (b - a) > max_lines
                                    or (heading and heading[0] <= 2)):
            chunks.append(current)
            current = None
        current = (a, b) if current is None else (current[0], b)
    if current is not None:
        chunks.append(current)
    return [Chunk(a + 1, b, lines[a:b], paths[a]) for a, b in chunks]


def _norm(s):
    s = s.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", s).strip()


def check_citation(text, line, value, window=2):
    lines, info = _scan(text)
    if not 1 <= line <= len(lines):
        return False
    want = _norm(value)
    if not want:
        return False
    for n in range(max(1, line - window), min(len(lines), line + window) + 1):
        if want in _norm(lines[n - 1]):
            return True
    return any(want == _norm(t) for t in _paths(info)[line - 1])
