"""Builds the public branch: a sanitised snapshot of the private branch, with history of its own.

Only committed files are used, never the working tree, so untracked and ignored files cannot leak. The
snapshot is built in a temporary git index from the source branch's latest commit: files listed under
"exclude" in tooling/public.json are left out, files under "replace" get public stand-ins, and every
file name, file and commit message is scanned for the "forbidden" patterns (home folders, email
addresses, API keys). One match stops the run before anything is written.

Each run adds one commit to the public branch whose parent is the previous snapshot, never a private
commit, so the private history is never part of the public branch. Nothing is pushed.

Extra private patterns, such as a real name or address, go in tooling/public.local.json (not committed),
as {"forbidden": [...]}, so the patterns themselves are never published.

Usage, from the project root:
  python tooling/public_snapshot.py --dry-run     build and scan, change nothing
  python tooling/public_snapshot.py               build, scan and commit to the public branch
  python tooling/public_snapshot.py -m "Text"     the same, with your own commit message
"""
import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_TRAILER = "Snapshot-of:"


def git(*args, env=None, data=None, check=True):
    out = subprocess.run(["git", *args], cwd=ROOT, env=env, input=data, capture_output=True, check=False)
    if check and out.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{out.stderr.decode(errors='replace')}")
    return out.stdout


def git_text(*args, **kw):
    return git(*args, **kw).decode("utf-8", errors="replace").strip()


def load_settings():
    settings = json.loads((ROOT / "tooling" / "public.json").read_text(encoding="utf-8-sig"))
    local = ROOT / "tooling" / "public.local.json"
    if local.exists():
        settings["forbidden"] += json.loads(local.read_text(encoding="utf-8-sig")).get("forbidden", [])
    return settings


def build_tree(source, settings):
    """The sanitised tree's id and its file list, built in a temporary index so the real one is untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git("read-tree", source, env=env)
        files = git_text("ls-files", env=env).splitlines()
        gone = [f for f in files if any(fnmatch.fnmatchcase(f, pattern) for pattern in settings["exclude"])]
        if gone:
            git("update-index", "--force-remove", "--", *gone, env=env)
        for path, stand_in in settings.get("replace", {}).items():
            blob = git_text("hash-object", "-w", "--", str(ROOT / stand_in))
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        return git_text("write-tree", env=env), git_text("ls-files", env=env).splitlines()


def scan(tree, files, message, settings):
    """Every forbidden match in file names, file contents and the commit message, as readable lines."""
    forbidden = [re.compile(p) for p in settings["forbidden"]]
    allowed = [re.compile(p) for p in settings.get("allow", [])]

    def hits(text):
        for pattern in forbidden:
            for m in pattern.finditer(text):
                if not any(a.search(m.group(0)) for a in allowed):
                    yield m

    found = []
    for path in files:
        found += [f"{path} (file name): {m.group(0)}" for m in hits(path)]
        text = git("cat-file", "blob", f"{tree}:{path}").decode("utf-8", errors="replace")
        for m in hits(text):
            line = text.count("\n", 0, m.start()) + 1
            found.append(f"{path}:{line}: {m.group(0)}")
    found += [f"commit message: {m.group(0)}" for m in hits(message)]
    return found


def last_snapshot(branch):
    """The public branch's tip and the source commit it was made from, or (None, None) for the first run."""
    tip = git_text("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False) or None
    if not tip:
        return None, None
    body = git_text("log", "-1", "--format=%B", tip)
    source = next((l.split(":", 1)[1].strip() for l in body.splitlines() if l.startswith(SOURCE_TRAILER)), None)
    return tip, source


def default_message(source, previous_source):
    span = f"{previous_source}..{source}" if previous_source else source
    subjects = git_text("log", "--reverse", "--format=- %s", span).splitlines()
    head = f"Snapshot, {date.today().isoformat()}"
    if not previous_source:
        return f"{head}: first public version\n\nThe project as of this date; earlier history stays private."
    return f"{head}\n\nChanges since the last snapshot:\n" + "\n".join(subjects)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="build and scan only; change nothing")
    parser.add_argument("-m", "--message", help="commit message (default: a dated list of the changes)")
    args = parser.parse_args()

    settings = load_settings()
    source = git_text("rev-parse", "--verify", settings["source"])
    tip, previous_source = last_snapshot(settings["branch"])
    tree, files = build_tree(source, settings)
    message = (args.message or default_message(source, previous_source)) + f"\n\n{SOURCE_TRAILER} {source[:12]}\n"

    print(f"Source {settings['source']} at {source[:12]}: {len(files)} files after excluding "
          f"{', '.join(settings['exclude'])}")
    leaks = scan(tree, files, message, settings)
    if leaks:
        print(f"\nStopped: {len(leaks)} forbidden match(es). Fix them in {settings['source']}, or exclude the file "
              "in tooling/public.json, then run again.")
        print("\n".join(f"  {leak}" for leak in leaks))
        sys.exit(1)
    print("Scan clean: no home folders, email addresses or keys in file names, files or the message.")

    if tip:
        changed = git_text("diff", "--stat", tip, tree)
        if not changed:
            print(f"Nothing to publish: {settings['branch']} already matches.")
            return
        print(f"\nChanges against the current {settings['branch']} branch:\n{changed}")
    if args.dry_run:
        print(f"\nDry run: {settings['branch']} not changed. Message would be:\n\n{message}")
        return

    parents = ["-p", tip] if tip else []
    commit = git_text("commit-tree", tree, *parents, data=message.encode("utf-8"))
    # Passing the old tip makes the update fail if the branch moved while this ran.
    git("update-ref", f"refs/heads/{settings['branch']}", commit, tip or "")
    print(f"\n{settings['branch']} is now {commit[:12]}. Nothing was pushed.")


if __name__ == "__main__":
    main()
