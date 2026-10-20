# Installing hermes-job-drop

## 1. Prerequisites

| Need | Why | Check |
|---|---|---|
| Hermes with the Discord gateway configured | The trigger: you mention the bot with a job link | the bot answers a mention in your channel |
| `discord.require_mention: true` (the default) | So a bare link in a busy channel does not start an application | your Hermes config |
| Google Chrome or Chromium | Drives forms in your signed-in profile; renders resume PDFs headlessly | `google-chrome --version` |
| Python 3.9+ | Installer and engine | `python3 --version` |
| PyYAML | Reading `config.yaml` / `profile.yaml` | `python3 -c "import yaml"` |

Optional Python packages (the kit works without them; features that need them say so):

| Package | Used for |
|---|---|
| `pypdf` (or `pdfplumber`) | Extracting text from PDF resumes during profile ingestion |
| `python-docx` | Extracting text from DOCX documents during profile ingestion |
| `weasyprint` | Fallback PDF renderer if Chrome is unavailable (needs pango/cairo system libraries) |

```bash
python3 -m pip install --user pyyaml pypdf python-docx
```

## 2. Run the installer

```bash
bash install.sh            # or: python3 install.py
```

It creates:

```
~/.hermes/jobdrop/
├── config.yaml              # the six model slots — edit this
├── profile.template.yaml    # the profile schema, fully commented
├── templates/
│   ├── resume.html          # your resume template — edit freely
│   └── cover_letter.md      # your cover-letter template — edit freely
├── applications/            # per-application PDFs and evidence
└── ledger.db                # the submission ledger (SQLite)
~/.hermes/skills/hermes-job-drop/
├── SKILL.md, references/    # the procedure Hermes follows
└── scripts/                 # the engine
```

Re-running is safe: your `config.yaml`, profile template and templates are **never
overwritten** unless you pass `--force`. The skill and scripts are refreshed every time.

Use a specific interpreter with `PYTHON=/path/to/python3 bash install.sh`.

## 3. Build your profile from your own documents

The fast path — no hand-written YAML:

```bash
python3 ~/.hermes/skills/hermes-job-drop/scripts/ingest_profile.py ~/my-career
```

Point it at any folder: PDFs of your resumes (the main input), DOCX/MD/TXT cover letters and
writing samples, an HTML resume, or a `profile.yaml`/`.json` you already keep (used as-is). It
writes a **draft** to `~/.hermes/jobdrop/profile.yaml` and reports every field it could not
ground — it never invents a contact detail or a claim. Review the draft once; after that it is
the single source of truth for every application.

Manual path: copy `~/.hermes/jobdrop/profile.template.yaml` to `profile.yaml` and fill it in.
Mark your important roles `core: true` — they will appear on every resume, and the build
fails loudly rather than silently dropping one.

The `answers:` section (salary, notice period, EEO choices, "how did you hear") is optional.
Anything left empty makes the bot ask you when a form requires it, rather than guess.

## 4. Choose your models

Each of the six slots in `~/.hermes/jobdrop/config.yaml` names its own `model` and
`provider`. Blank slots are an error — there is no fallback model.

| Slot | Does | Pick something with |
|---|---|---|
| `vision` | Reads screenshots of forms and challenges | image input |
| `tooling` | Field/option matching, ledger writes | reliable function calling; a small fast model is fine |
| `browser` | Drives the form end to end | tools + vision + long context; your strongest model |
| `python` | Writes small helpers for awkward portal mechanics | good code + tool use |
| `resume` | Picks which verified bullets to show for a job | careful instruction following; small is fine |
| `cover_letter` | Writes the letter | strong long-form writing + JSON discipline |

Keys: set `api_key_env` to the **name** of an environment variable (never the key itself).
If omitted, the provider's usual variable is used (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`OPENROUTER_API_KEY`, `GEMINI_API_KEY`, …). Local servers (`provider: ollama`, or any
OpenAI-compatible server via `base_url`) need no key.

`browser` may instead carry `command:` — a shell command that starts an external agent to do
the driving. When present it wins over `model`/`provider` for that slot.

See `examples/example_config.yaml` for a filled-in config.

## 5. Check everything

```bash
python3 ~/.hermes/skills/hermes-job-drop/scripts/config.py --doctor
# or, from the repo:
bash install.sh --doctor
```

For each slot: the resolved model/provider (or command), `key_present=True|False` (never the
key), and `endpoint=ok|fail` from one minimal request. Exit code 0 means every slot is usable.

```bash
bash install.sh --audit-user-data
```

Confirms `~/.hermes/jobdrop/` is not tracked by any git repository (useful if your home
directory is a dotfiles repo).

## 6. Use it

Post a job link in your Discord channel and mention the bot, optionally with a one-line note
("referral from a former colleague", "remote only"). It replies in a thread with SUBMITTED,
PARKED (with the exact question and options), DUPLICATE or FAILED. Re-posting the same link
never applies twice; re-posting a parked or failed one resumes it.

## Troubleshooting

See [`hermes-job-drop/references/troubleshooting.md`](hermes-job-drop/references/troubleshooting.md).
Common ones:

- **`missing model slot(s)`** — add the named slot to `config.yaml`.
- **`key_present=False`** — the env var isn't set where Hermes runs; export it and restart Hermes.
- **`PyYAML is required`** — `python3 -m pip install --user pyyaml`, or run with an interpreter
  that has it (`PYTHON=... bash install.sh --doctor`).
- **Chrome render hangs** — renders always run under `timeout 60` with a throwaway profile; a
  PDF present after the timeout is normally complete.
