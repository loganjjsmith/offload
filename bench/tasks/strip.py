"""Remove comments (and Python docstrings) from source code without touching string literals.

Used to test "reading terse": giving a model code without comments to read, while it still writes
normally. Lines left empty by the removal are dropped.
"""
import ast
import io
import tokenize


def _drop_empty(text, original_blank):
    """Drop lines that became empty, keeping lines that were blank to begin with."""
    out = []
    for line, was_blank in zip(text.split("\n"), original_blank):
        if line.strip() or was_blank:
            out.append(line.rstrip())
    return "\n".join(out)


def strip_python(code):
    tree = ast.parse(code)
    docstring_lines = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
            docstring_lines.update(range(body[0].lineno, body[0].end_lineno + 1))
    lines = code.split("\n")
    comments = {}
    for tok in tokenize.generate_tokens(io.StringIO(code).readline):
        if tok.type == tokenize.COMMENT:
            comments.setdefault(tok.start[0], tok.start[1])
    kept = []
    for i, line in enumerate(lines, start=1):
        if i in docstring_lines:
            line = ""
        elif i in comments:
            line = line[:comments[i]].rstrip()
        kept.append(line)
    return _drop_empty("\n".join(kept), [not line.strip() for line in lines])


def strip_c_like(code, template_strings=False):
    """C# and TypeScript: // and /* */ comments outside "...", '...' and (TypeScript) `...` strings."""
    out, i, n = [], 0, len(code)
    while i < n:
        c, nxt = code[i], code[i + 1] if i + 1 < n else ""
        if c in "\"'" or (template_strings and c == "`"):
            j = i + 1
            while j < n and code[j] != c:
                j += 2 if code[j] == "\\" else 1
            out.append(code[i:j + 1])
            i = j + 1
        elif c == "@" and nxt == '"':  # C# verbatim string: "" is an escaped quote
            j = i + 2
            while j < n and not (code[j] == '"' and (j + 1 >= n or code[j + 1] != '"')):
                j += 2 if code[j] == '"' else 1
            out.append(code[i:j + 1])
            i = j + 1
        elif c == "/" and nxt == "/":
            while i < n and code[i] != "\n":
                i += 1
        elif c == "/" and nxt == "*":
            end = code.find("*/", i + 2)
            i = n if end < 0 else end + 2
        else:
            out.append(c)
            i += 1
    stripped = "".join(out)
    return _drop_empty(stripped, [not line.strip() for line in code.split("\n")]) \
        if stripped.count("\n") == code.count("\n") else "\n".join(l.rstrip() for l in stripped.split("\n") if l.strip())


def strip_comments(code, language):
    if language == "python":
        return strip_python(code)
    return strip_c_like(code, template_strings=language == "typescript")
