# Publishing the public snapshot

The project has two faces. `main` is the private working branch with its full history and the handoff
log. The public face is a sanitised snapshot of `main`, made by `tooling/public_snapshot.py`, kept in a
separate public repository with history of its own. The private history never goes there.

The public repository is its own git folder beside this one (`offload-public`), with its own commit
identity set at repository level: the public GitHub account's no-reply address, so no personal address is
ever in a public commit. It is pushed from GitHub Desktop, signed in to the public account.

## What the snapshot leaves out

Set in `tooling/public.json`:

- `docs/HANDOFF.md`, the session log, replaced by a short note (`tooling/public/HANDOFF.md`)
- the Remote Control scripts in `tooling/`, which are about this one machine's remote access
- everything not committed: the virtual environment, raw benchmark logs, server call logs,
  `server/config.local.json`, `scratch/`, `private/`, and agent settings
- every private commit: only the snapshot's files are copied, never history

Before anything is written, every file name and file is scanned for home-folder paths, email addresses
(other than GitHub's and Anthropic's no-reply addresses) and API-key shapes. One match stops the run.
Extra private patterns, such as other projects' names, go in `tooling/public.local.json` (not committed):
`{ "forbidden": ["pattern one", "pattern two"] }`, so the patterns themselves are never published.

What the scan cannot judge is tone and context. Committed files are written to be publishable: other
projects are named only in the uncommitted `private/` folder, examples are generic, and samples run on
public material only. Read the changes once more before each push.

## Updating the public repository

From this project's root, in PowerShell, after work lands on `main`:

1. Check first; this writes nothing:
   ```powershell
   .venv\Scripts\python tooling\public_snapshot.py --export ..\offload-public --dry-run
   ```
2. Write the snapshot into the public repository's folder. Files the snapshot no longer has are deleted
   there; its history is untouched, and nothing is committed:
   ```powershell
   .venv\Scripts\python tooling\public_snapshot.py --export ..\offload-public
   ```
3. Review and commit in GitHub Desktop (or `git -C ..\offload-public diff --stat` and a commit there),
   with a message that describes the changes for a public reader. Then push from GitHub Desktop.

Check the commit identity once if in doubt: `git -C ..\offload-public config user.email` must print the
no-reply address.

## The older route: a branch in this repository

`tooling/public_snapshot.py` without `--export` builds the same snapshot as commits on a `public` branch
of this repository, with history of its own (`--dry-run` to check, `-m "Text"` for the message). It needs a
remote that only ever receives that branch:

```powershell
git remote add public https://github.com/<account>/offload.git
git config remote.public.push refs/heads/public:refs/heads/main
git push public
```

Never `git push --all public` or `git push --mirror public`: those would send `main` too. The separate
repository above avoids that risk altogether, which is why it is the route in use.

## After the first push

- On the repository page: add a description and topics (for example `local-llm`, `mcp`, `benchmarking`,
  `amd`, `rocm`, `vulkan`, `claude-code`), and pin it on your profile.
- Licence: without one, people may read the code but have no right to reuse it. MIT is the usual choice
  for a portfolio project that others may borrow from.
- GitHub's secret scanning is on by default for public repositories and is a second net behind the
  snapshot's own scan.
