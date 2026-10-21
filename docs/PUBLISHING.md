# Publishing the public snapshot

The project has two faces. `main` is the private working branch with its full history and the handoff
log. `public` is a sanitised snapshot of `main` with history of its own, made by
`tooling/public_snapshot.py`, and it is the only branch that ever goes to a public repository.

GitHub sets visibility per repository, not per branch, so the public snapshot lives in its own public
repository. The private repository (if there is one) never needs the `public` branch, and the public
repository must never receive `main`.

## What the snapshot leaves out

Set in `tooling/public.json`:

- `docs/HANDOFF.md`, the session log, replaced by a short note (`tooling/public/HANDOFF.md`)
- the Remote Control scripts in `tooling/`, which are about this one machine's remote access
- everything not committed: the virtual environment, raw benchmark logs, server call logs,
  `server/config.local.json`, `scratch/`, and agent settings
- every private commit: the public branch starts from one snapshot commit and shares no history with `main`

Before anything is written, every file name, file and commit message is scanned for home-folder paths,
email addresses (other than GitHub's and Anthropic's no-reply addresses) and API-key shapes. One match
stops the run. Extra private patterns, such as a phone number or street name, go in
`tooling/public.local.json` (not committed): `{ "forbidden": ["pattern one", "pattern two"] }`.

What the scan cannot judge is tone and context. Committed files are written to be publishable: other
projects are named only in the uncommitted `private/` folder, and examples are generic. Names that must
never appear (personal handles, other projects, the storage server) are patterns in
`tooling/public.local.json`, so a slip stops the snapshot. Read the snapshot once more before each push.

## First publication

In PowerShell, from the project root:

1. Review what will be public. This lists the files and opens nothing on the internet:
   ```powershell
   git show public --stat
   git show public:README.md
   ```
2. Create an empty **public** repository on GitHub, for example `offload`, with no README, licence or
   .gitignore (the snapshot has its own). On github.com: New repository, Public. Or with the GitHub CLI:
   ```powershell
   gh repo create offload --public --description "Local AI delegation for a cloud coding agent, decided by measurement"
   ```
3. Add it as a remote that can only ever receive the `public` branch, as that repository's `main`:
   ```powershell
   git remote add public https://github.com/loganjjsmith/offload.git
   git config remote.public.push refs/heads/public:refs/heads/main
   ```
4. Push. With the push setting above, a plain `git push public` sends only the snapshot:
   ```powershell
   git push public
   ```
   Never run `git push --all public` or `git push --mirror public`: those would send `main` too.

## Updating it later

After work lands on `main`, from the project root:

```powershell
.venv\Scripts\python tooling\public_snapshot.py --dry-run
.venv\Scripts\python tooling\public_snapshot.py
git push public
```

The first command shows what changed and the commit message it would write (a dated list of the
`main` commit subjects since the last snapshot); pass `-m "Your message"` to write your own. Each run adds
one commit on top of the last snapshot, so the public history grows as a series of dated snapshots.

## After the first push

- On the repository page: add a description and topics (for example `local-llm`, `mcp`, `benchmarking`,
  `amd`, `rocm`, `vulkan`, `claude-code`), and pin it on your profile.
- Licence: without one, people may read the code but have no right to reuse it. MIT is the usual choice
  for a portfolio project that others may borrow from.
- GitHub's secret scanning is on by default for public repositories and is a second net behind the
  snapshot's own scan.
