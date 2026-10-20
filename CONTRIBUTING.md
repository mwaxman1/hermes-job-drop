# Contributing

Thanks for helping. Two rules matter more than anything else here.

## 1. No personal data, ever

This repo is public. It ships templates, docs, code and a **synthetic** example persona —
nothing about any real person.

- Never commit a real resume, cover letter, profile, answer, job URL, application ID,
  database, `.env`, key, cookie, or screenshot of a real form.
- Examples use invented names and employers, `example.com`/`example.org` addresses, and
  phone numbers in the fictional `555-01xx` range.
- Use `~/` in docs, never an absolute home path.

The audit enforces this on every push and pull request, and you should run it before
committing:

```bash
python3 scripts/audit_no_personal_data.py
```

It scans git-tracked files for non-example emails, phone-shaped numbers, LinkedIn profile
URLs, `/home/<name>/` paths, street addresses, and banned file types (`.env*`, `*.pem`,
`*.key`, `*.p12`, `*.db`, `*.sqlite*`, `*.pdf`, `*.docx`, images under `data/`).

To ban strings specific to you (your name, your employers), list them one per line in
`personal-denylist.local.txt` at the repo root. It is gitignored, so the audit uses it
locally without the strings ever being committed.

## 2. Never fabricate

Changes to the skill or engine must preserve the doctrine in `hermes-job-drop/SKILL.md`:
claims come only from the user's verified profile; anything ungrounded parks and asks;
submit is the default; the ledger is the record.

## Development

```bash
python3 -m pip install pytest pyyaml
python3 -m pytest tests/ -q
python3 scripts/audit_no_personal_data.py
```

- Scripts are stdlib-first. A third-party dependency must be optional: import it lazily and
  fail with a clear message saying what to install.
- Keep the six model slots the only way a model is chosen. No hard-coded model names in code.
- If you change `templates/resume.html`, render it to PDF with Chrome, rasterize it, and look
  at the image before opening a PR (`hermes-job-drop/references/resume-builder.md`, "The visual
  gate"). Attach the PNG to the PR, rendered from `examples/example_profile.yaml` only.
