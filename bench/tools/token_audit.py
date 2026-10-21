"""Count how much tool output entered the cloud model's context, by project and by tool.

Reads Claude Code transcripts (~/.claude/projects/**/*.jsonl). Sizes are characters; tokens are
estimated at four characters each.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path.home() / ".claude" / "projects"


def project_group(folder: str) -> str:
    if "Game-Dev" in folder:
        return "Unity game"
    if "Offload" in folder:
        return "Offload"
    if "Autonomous" in folder:
        return "Autonomous Coding"
    return "other"


def bash_category(command: str) -> str:
    words = re.findall(r"[^\s;|&]+", command.strip())
    skip = {"cd", "set", "export", "&", "."}
    words = [w for w in words if w not in skip and not w.startswith("$")]
    if not words:
        return "?"
    head = Path(words[0].strip("\"'")).name.lower()
    if head in {"git", "dotnet", "python", "python.exe", "npm", "npx", "docker", "lms", "ollama", "unity", "gh"} and len(words) > 1:
        return f"{head} {words[1].strip(chr(34) + chr(39))}"[:40]
    return head[:40]


def result_text(block) -> tuple[int, int]:
    content = block.get("content")
    if isinstance(content, str):
        return len(content), 0
    chars, images = 0, 0
    for part in content or []:
        if part.get("type") == "text":
            chars += len(part.get("text", ""))
        elif part.get("type") == "image":
            images += 1
    return chars, images


def main() -> None:
    tool_of = {}
    by_tool = defaultdict(lambda: [0, 0, 0])  # chars, calls, largest
    by_project = defaultdict(int)
    images = 0
    for path in ROOT.rglob("*.jsonl"):
        group = project_group(path.relative_to(ROOT).parts[0])
        for line in path.open(encoding="utf-8", errors="replace"):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = (entry.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    name = block.get("name", "?")
                    inp = block.get("input") or {}
                    if name in ("Bash", "PowerShell"):
                        name = f"{name}: {bash_category(str(inp.get('command', '')))}"
                    elif name == "Read":
                        suffix = Path(str(inp.get("file_path", ""))).suffix.lower() or "(none)"
                        name = f"Read {suffix}"
                    tool_of[block.get("id")] = name
                elif block.get("type") == "tool_result":
                    chars, imgs = result_text(block)
                    images += imgs
                    name = tool_of.get(block.get("tool_use_id"), "?")
                    row = by_tool[(group, name)]
                    row[0] += chars
                    row[1] += 1
                    row[2] = max(row[2], chars)
                    by_project[group] += chars

    print("Tool output entering context, estimated tokens (chars / 4)\n")
    for group, chars in sorted(by_project.items(), key=lambda kv: -kv[1]):
        print(f"{group:20} {chars // 4:>12,}")
    print(f"images returned by tools: {images}\n")
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    print(f"{'project':18} {'tool':45} {'est tokens':>12} {'calls':>7} {'avg':>7} {'largest':>8}")
    rows = sorted(by_tool.items(), key=lambda kv: -kv[1][0])[:limit]
    for (group, name), (chars, calls, largest) in rows:
        print(f"{group:18} {name:45} {chars // 4:>12,} {calls:>7} {chars // 4 // calls:>7,} {largest // 4:>8,}")


if __name__ == "__main__":
    main()
