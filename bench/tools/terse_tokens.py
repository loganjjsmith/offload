"""Token cost of C# files as written, without comments, and minified, using the loaded model's tokenizer."""
import json
import re
import sys
import urllib.request

URL = "http://127.0.0.1:1234/v1/chat/completions"


def tokens(text):
    body = {"model": "bench", "messages": [{"role": "user", "content": text}], "max_tokens": 1,
            "extra_body": {}, "reasoning_effort": "none"}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())["usage"]["prompt_tokens"]


STRING = r'@?"(?:[^"\\]|\\.|"")*"|\'(?:[^\'\\]|\\.)\''


def strip_comments(src):
    out = []
    for m in re.finditer(STRING + r"|//[^\n]*|/\*.*?\*/|.", src, re.DOTALL):
        t = m.group(0)
        out.append("" if t.startswith(("//", "/*")) else t)
    return re.sub(r"\n\s*\n+", "\n", "".join(out))


def minify(src):
    src = strip_comments(src)
    parts = []
    for m in re.finditer(STRING + r"|\s+|.", src, re.DOTALL):
        t = m.group(0)
        parts.append(" " if t.isspace() else t)
    text = "".join(parts)
    # drop spaces next to punctuation, keep them between words
    return re.sub(r" ?([{}();,=<>+\-*/&|!?:\[\]]) ?", r"\1", text).strip()


def main(paths):
    base = tokens("")
    rows = []
    for p in paths:
        src = open(p, encoding="utf-8-sig").read()
        variants = {"as written": src, "no comments": strip_comments(src), "minified": minify(src)}
        counts = {k: tokens(v) - base for k, v in variants.items()}
        rows.append((p.split("\\")[-1], counts))
        print(p.split("\\")[-1], counts, flush=True)
    total = {k: sum(c[k] for _, c in rows) for k in rows[0][1]}
    print("TOTAL", total, {k: f"{100 * (1 - v / total['as written']):.0f}% saved" for k, v in total.items()})


if __name__ == "__main__":
    main(sys.argv[1:])
