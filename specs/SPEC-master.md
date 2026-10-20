# SPEC — hermes-job-drop (public, redistributable)

Status: DESIGN. Owner: Mike Waxman. Target: a PUBLIC GitHub repo a non-author can clone
and run against Hermes + Discord in minutes, with ZERO of the author's personal data in it.

---

## 0. What we are building

A **kit** that turns "post a job link in Discord and tag the bot" into a real, submitted
application, on someone else's machine, using their own Chrome, their own models, and their
own resume/cover-letter templates.

It is NOT a fork of the author's private job-search repo. It is a clean-room generalization:
the *doctrine* (how to drive an ATS form, what to never fabricate, when to submit) and the
*engine* (deterministic resume build, role-aware LLM calls, a submission ledger) are reusable;
the *data* (a person's profile, employers, answers, URLs, credentials) is not.

**Success test (Slice 2 end-state):** a fresh machine, a fresh clone, a filled-in profile and
templates, and the documented command sequence produces a real PDF resume and a real cover
letter for a given job URL, records the attempt in the ledger, and the skill drives the form
to a click on Submit. No author data anywhere in the tree.

---

## 1. Non-negotiables

1. **No personal data from the source lane.** See §3. Enforced by an automated audit (§9) that
   runs in CI and fails the build.
2. **No fabrication.** The kit never invents an answer, a credential, an experience claim, an
   EEO answer, or a referral source. If nothing grounded can be said, the item parks
   honestly and says why. Parking is a correct outcome, not a failure.
3. **Submit is the default.** Open the form, fill it, solve the captcha, click Submit, confirm,
   record it, move on. Leaving a filled form for a human to click is NOT a completed run.
   Exception: an answer only the user can give (see §7.4).
4. **Vision first, never hand-written selectors.** The *form-driving* model reads the form
   (screenshot + DOM) and decides what to do. Do not write a bespoke Python DOM-selector driver
   for a new ATS shape — that path burns a day per portal and is what this kit exists to avoid.
   Python is for *mechanics* (uploads, ledger writes, file handling), not for *perception*.
5. **One application at a time, in the user's own signed-in Chrome.** Never a throwaway profile.
   Never close or reuse a tab you did not open in this run.
6. **The ledger is the record.** Report state from the ledger/database, never from a log line.
   A lane that says "submitted" and a ledger row that says otherwise — the ledger wins.
7. **No purchases, no sends, no contracts.** The kit may fill forms and submit applications
   (that is the entire point) but it must not buy anything, sign anything, or post publicly
   without an explicit human confirmation. The kit must ship a hard gate for this.

---

## 2. What generalizes from the source lane

The source lane is a private, single-operator job-search system. The following were inspected
and are the reusable parts. Read them from the source tree; **copy the technique, not the data.**

| Source artifact | Generalizes? | How it lands in this repo |
|---|---|---|
| `engine/packages/profile_resume.py` (703 lines) | YES — the deterministic resume builder | `scripts/build_resume.py`, re-pointed at a user-supplied profile + template. The "verified profile is the only source of resume claims" invariant is preserved exactly. |
| `engine/cover_letter_composer.py` / `_generator.py` | YES — the letter pipeline and its gates | `scripts/build_cover_letter.py` + `references/cover-letter-gates.md`. Gates (length, paragraph count, register, no tool-name leakage) are ported as rules, not as the author's voice. |
| `engine/core/llm_client.py` | YES — one env-driven client | `scripts/llm.py`, extended to **per-slot** model/provider/key/base_url. |
| `engine/core/field_resolver.py`, `fill_form_deterministic.py` | PARTIAL — field-label matching heuristics | `scripts/field_matching.py`, reduced to the reusable matching rules only. |
| `engine/captcha_solver.py` | YES — solve-never-refuse posture | `references/captcha-and-verification.md` (doctrine) + optional solver hook. |
| `engine/core/answer_engine.py` + a personal answer bank | PATTERN ONLY | `references/answer-grounding.md` — how to ground every answer in the user's own files. The personal bank is **not** copied. |
| The ATS-form-shape knowledge (per-ATS commit recipes, upload traps, confirmation routes) | YES — the highest-value asset | `references/ats-form-shapes.md` and siblings. Generalized: no personal answers, no personal URLs, no personal locations; described as *shape* + *recipe*, not *the author's transaction*. |
| The submission-recording discipline (evidence shape, readback) | YES | `references/submission-recording.md` + `scripts/ledger.py`. |
| The Discord drop-lane plumbing (cursor ingest, reaction acks, per-day thread) | MAYBE | Not the primary path. See §7.1 — the mention-triggered gateway path replaces it. A ledger + ack-reaction is kept. |
| The live Postgres schema (Neon, `jobhunt.*` schema) | NO — over-built for a single user | Replaced with a local SQLite ledger (§7.5). |
| The author's `data/*.yaml` (profile, answer bank, targets, campaigns) | **NO — PERSONAL** | Never read into this repo. See §3. |

**DO NOT READ THE SOURCE TREE.** The source lane lives at `/home/mike/projects/jobhunt`. This
repo's builder MUST NOT open it, grep it, or copy from it. Reason: the source tree contains
the author's personal data, and a single read is a channel through which that data could leak
into a public repo. **This spec is the complete input.** Everything the builder needs —
the architecture, the doctrine, the file list, the acceptance criteria — is written here.
If something is not in this spec, implement the most reasonable general version and note it
as an open question in the report. Never go looking for the original.

---

## 3. The privacy boundary (hard)

### 3.1 What must NEVER enter this repo

- The author's name, email addresses, phone numbers, home city/state, postal address.
- The author's employer names, non-profit names, client names, company targets.
- The author's LinkedIn/portfolio/personal-domain URLs, personal site links, tracking URLs.
- The author's resume files, cover letters, PDF/DOCX artifacts, profile YAML, answer bank.
- The author's job-posting URLs, application IDs, canonical job rows, database dumps.
- Any `.env`, secret, token, key, session file, or cookie.
- Any absolute home-directory path (`/home/<name>/...`) — use `~/` or a resolved runtime path.
- Any internal tool/agent name that would leak the source setup (e.g. an internal codegen CLI,
  a private channel name, a private DB name, a private skill namespace).

### 3.2 What the repo ships instead

- **Templates with placeholders**: `{{FIRST_NAME}}`, `{{EMAIL}}`, `{{CITY}}, {{STATE}}`, etc.
- A **fictional example profile** under `examples/` — a synthetic persona with invented
  employers and invented contact details, clearly labelled as synthetic, using
  `example.com` / `example.org` addresses so no real mailbox can be confused with it.
- A **privacy audit** that fails CI on generic personal-data patterns, so a future contributor
  cannot leak by accident either.

### 3.3 The audit (must exist and must run in CI)

`scripts/audit_no_personal_data.py`, run over **git-tracked files only** (`git ls-files`):

- **Banned file types tracked**: `.env`, `.env.*` (except `.env.example`), `*.pem`, `*.key`,
  `*.p12`, `*.sqlite`, `*.sqlite3`, `*.db`, `*.pdf` (any), `*.docx`, `*.png`/`*.jpg` in `data/`.
  Note: a resume *template* is HTML/Markdown/YAML — never a binary PDF.
- **Generic personal-data patterns** in tracked text files:
  - email addresses not on an allowlist of `example.com|example.org|example.net|localhost`
    and not a docs placeholder like `you@<...>`;
  - phone-number-shaped runs (7+ consecutive digits, allowing `+`, `-`, `(`, `)`, space, `.`);
  - `linkedin.com/in/<something>` other than an `example` slug;
  - absolute paths matching `/home/<realname>/` (allow `/home/<user>/` only if the segment is
    literally `user`, `runner`, or `ci`);
  - street-address-shaped strings (`\d+ [A-Z][a-z]+ (Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Blvd|Boulevard|Way|Court|Ct)`);
  - any `{{...}}`-style template placeholder is ALLOWED; any *concrete* personal value in a
    `data/` or `templates/` file is not.
- **A local denylist**: `personal-denylist.local.txt` (gitignored) — a developer can add
  specific strings to ban (e.g. the author's employer names) without committing them. When
  absent, the audit still runs the generic rules and prints a notice.
- **The user-data check**: `install.py --audit-user-data` verifies the user's own data
  directory (`~/.hermes/jobdrop/`) is gitignored and that no file from it is tracked.

The audit must print the file, line number, pattern name, and the offending line for every
hit, and exit non-zero. It must be runnable standalone (`python3 scripts/audit_no_personal_data.py`)
and by CI.

---

## 4. Model slots — the user chooses their own models

The user MUST be able to pick, per concern, which model does the work. This is a first-class
config surface, not an env-var footnote. Six slots:

| Slot | What it does | Typical capability needed |
|---|---|---|
| `vision` | Reads screenshots / page images — the form-shape perception step | image input |
| `tooling` | Tool-calling model for the deterministic mechanics (field matching, option matching, ledger writes) | function calling |
| `browser` | The model that *drives* the browser: reads the form, decides the next action, clicks/types | tools + vision, long context |
| `python` | Writes/adapts the Python driver when a portal needs a mechanical helper | code + tool use |
| `resume` | Resume tailoring: selects verified bullets, writes the summary line | text + instruction following |
| `cover_letter` | Cover letter composition | long-form writing + JSON discipline |

**Config shape** (`~/.hermes/jobdrop/config.yaml`, template at `config/config.template.yaml`):

```yaml
version: 1
models:
  vision:
    model: "<slug>"
    provider: "<provider>"
    base_url: "<optional>"
    api_key_env: "<optional env var name>"
    temperature: 0.2
  tooling:   { model: "...", provider: "...", api_key_env: "..." }
  browser:   { model: "...", provider: "...", api_key_env: "..." }
  python:    { model: "...", provider: "...", api_key_env: "..." }
  resume:    { model: "...", provider: "...", api_key_env: "..." }
  cover_letter: { model: "...", provider: "...", api_key_env: "..." }
```

**Rules:**
- `model` and `provider` are REQUIRED for every slot. `base_url` and `api_key_env` optional
  (fall back to the provider's default endpoint and the ambient environment).
- The `browser` slot additionally MAY carry `command:` — a shell command that starts the
  driving session (e.g. a Claude Code tier launcher) — for users whose browser driving is
  done by an external coding agent rather than an in-process model. When `command` is present
  it wins over `model`/`provider` for that slot and the rest of the config still applies.
- **There is no default model.** A missing slot is a hard configuration error with a message
  naming the slot and the file to edit. The kit never silently falls back to some other
  provider's model.
- `scripts/config.py` loads and validates this file; every other script takes its client
  through `scripts/llm.py`, which resolves the slot and NEVER reads a model name from
  anywhere else.
- A `doctor` subcommand reports, per slot, the resolved model/provider, whether the key
  resolves to a non-empty value (never printing the value), and whether the endpoint is
  reachable. Reachability check = one minimal request; it must not print response bodies
  beyond a short ok/fail.

---

## 5. User-supplied inputs

The kit ships **templates**; the user supplies **content**. Three user-owned inputs:

### 5.1 `~/.hermes/jobdrop/profile.yaml` — the verified profile
The single source of truth for every claim the kit may make about the user. Schema is
defined by `templates/master_profile.template.yaml` (fully commented). It must contain at
minimum: personal contact block, summary, work experience (each with bullets), education,
skills, certifications, links.

**Invariant (ported from the source lane):** the resume and cover letter may only assert
what is in this file. A JD may *select* among the user's verified bullets; it may never
*rewrite* one. If the profile lacks a required core role, the build FAILS LOUDLY rather than
silently omitting it. Silent omission is the exact failure mode this design exists to prevent.

### 5.2 Resume template — `~/.hermes/jobdrop/templates/resume.html`
HTML + CSS, WeasyPrint-renderable, with `{{PLACEHOLDER}}` tokens the builder substitutes.
The shipped default template is a clean, ATS-friendly, single-column, print-ready document.
The user may replace it wholesale; the builder only requires that the template contain the
tokens the builder knows how to fill, and it must WARN (not fail) if the user's template
contains a token the builder does not know — otherwise a typo silently drops a section.

### 5.3 Cover-letter template — `~/.hermes/jobdrop/templates/cover_letter.md`
A Markdown template with `{{PLACEHOLDER}}` tokens (e.g. `{{GREETING}}`, `{{OPENING}}`,
`{{BODY_PARA_1}}`, `{{BODY_PARA_2}}`, `{{BODY_PARA_3}}`, `{{CLOSING}}`, `{{SIGNATURE}}`).
The builder asks the `cover_letter` slot model to produce the *content* for these slots; the
template owns the *form*. A user's template with different tokens works without code changes
as long as the builder's token map is satisfied by the slots it knows; unknown tokens warn.

**Both templates ship as files the user copies, edits, and keeps OUT of the repo** — they
live in `~/.hermes/jobdrop/`, never in the git tree.

---

## 6. Repo layout (public)

```
hermes-job-drop/
├── README.md                     # 5-minute quickstart, the front door
├── INSTALL.md                    # detailed setup, troubleshooting, model picking
├── LICENSE                       # MIT
├── CONTRIBUTING.md
├── .gitignore
├── .github/workflows/ci.yml      # audit + tests
├── install.sh                    # one-command installer
├── install.py                    # the installer's logic
├── config/
│   └── config.template.yaml      # the 6 model slots
├── templates/
│   ├── master_profile.template.yaml
│   ├── resume.html
│   └── cover_letter.md
├── examples/
│   ├── example_profile.yaml      # FICTIONAL persona
│   └── example_config.yaml
├── hermes-job-drop/              # ← the Hermes SKILL payload (copied into ~/.hermes/skills/)
│   ├── SKILL.md                  # the process doctrine
│   └── references/
│       ├── ats-form-shapes.md
│       ├── submission-recording.md
│       ├── answer-grounding.md
│       ├── captcha-and-verification.md
│       ├── cover-letter-gates.md
│       ├── resume-builder.md
│       └── troubleshooting.md
├── scripts/
│   ├── config.py
│   ├── llm.py
│   ├── profile.py
│   ├── field_matching.py
│   ├── build_resume.py
│   ├── build_cover_letter.py
│   ├── jd_extract.py
│   ├── ledger.py
│   ├── chrome_cdp.py             # fallback driver (Slice 3)
│   └── audit_no_personal_data.py
└── tests/
    ├── test_config.py
    ├── test_profile.py
    ├── test_resume.py
    ├── test_cover_letter.py
    ├── test_ledger.py
    └── test_audit.py
```

The skill payload directory is named `hermes-job-drop/` and is installed to
`~/.hermes/skills/hermes-job-drop/`. Its `SKILL.md` must be self-contained: a user who has
only the skill and a config can drive a submission.

---

## 7. Data flow

### 7.1 Trigger — the mention path (primary)

The user posts a job URL in a Discord channel and **mentions the Hermes bot** (or replies to
it). Hermes' existing Discord gateway receives the message and wakes a session. The skill
`hermes-job-drop` is the process authority for that session.

Why this and not a polling cron: the user already runs Hermes with a Discord bot; a
mention needs **no new credential, no new service, and no new channel** — it is one
`DISCORD_BOT_TOKEN` the user already had to set up for Hermes. A polling cron needs a second
bot token, a channel-id, a guild-id, and a cursor file. The mention path is strictly less
setup and strictly less to go wrong, which is the requirement here.

The kit's Discord requirement is therefore: **Hermes' Discord gateway is already configured.**
The kit adds: a skill, a config, a profile, templates, and the engine.

`discord.require_mention: true` (the default) is what makes a bare link in a busy channel
not fire the lane.

### 7.2 The run

1. **Parse the drop.** Extract the URL(s) and any trailing one-line note.
2. **Dedupe** against the ledger (normalized URL key) and the user's "already applied" list.
   A duplicate is a no-op with a clear reason — not a second application.
3. **Resolve the job** — fetch the posting text (`jd_extract.py`, using the `web_extract`
   provider or a plain fetch). Detect ATS family and the form's canonical apply URL.
4. **Build the resume** (`build_resume.py`): profile + JD → tailored PDF.
5. **Build the cover letter** (`build_cover_letter.py`): profile + JD → letter, via the
   `cover_letter` slot, through the letter gates.
6. **Drive the form** in the user's real Chrome, using the `browser` slot for perception and
   `tooling`/`python` slots for mechanics. Fill, solve, submit, confirm.
7. **Record** the outcome in the ledger with its evidence, then **report** in the Discord
   thread: what was submitted, to whom, with what documents; or what parked and why.

### 7.2b The visual gate on the resume template

The resume template is a **visual artifact**, and an adjective is never a criterion. A
resume template passes only when the rendered PDF has been **rendered and LOOKED at**:
- render `templates/resume.html` + the example profile to a PDF;
- rasterize it to PNG at page 1 (and page 2 if present);
- **open the PNG with the image-reading tool and actually look at it**;
- fail the build on: overlapping text, a clipped or cut-off right edge, a section header
  with no content under it, text running off the page, unreadable contrast, a summary that
  overflows its box, or a page break that splits a bullet from its role title.

Reporting "the template looks clean" without an inspected image is a FAIL, not a pass.
The builder must be able to do this (render → PNG → read image); if the environment cannot
rasterize, the SKILL.md must instruct the agent to screenshot the rendered HTML in Chrome
instead, and that screenshot is the gate artifact.

### 7.3 Two browser drivers, one interface

- **Preferred: the Hermes Chrome plugin** (`chrome_*` tools) — the user's own signed-in
  Chrome, no remote-debug port, no throwaway profile. If the plugin is present, use it.
- **Fallback: local CDP** (`scripts/chrome_cdp.py`, Slice 3) — launches the user's Chrome with
  a remote-debugging port for users who do not want the extension. Never a fresh/throwaway
  profile with no logged-in state unless the ATS needs no login.

Both implement one interface so the skill's procedure is identical either way.

### 7.4 Parking (the honest outcome)

If the only remaining field is one only the user can answer, the kit:
- does NOT guess and does NOT submit;
- records the park with the **verbatim field label** and the form's real options;
- asks the user in Discord with those options.

The skill must state this as a normal outcome, not an error.

### 7.5 The ledger

`~/.hermes/jobdrop/ledger.db` — SQLite, three tables:

- `drops` — id, url, url_key (unique), note, company, title, state, created_at, updated_at
- `submissions` — id, drop_id, ats, job_url, resume_path, cover_letter_path, confirmation_url,
  confirmation_text, submitted_at, method
- `events` — id, drop_id, event, detail, created_at

`state` ∈ `received | resolving | documents_ready | filling | submitted | parked | failed | duplicate`.
`url_key` is UNIQUE → a re-drop of an active or done item is a no-op.

The ledger is the report source of truth (§1.6). A run that says "submitted" while the row
says otherwise is a bug, and the audit of every run compares the report against the row.

---

## 8. Slice plan

Two Opus dispatches, same branch, second starts from the first's committed bytes.

### Slice 1 — the kit: architecture, doctrine, templates, installer, audit, CI
Deliver: repo skeleton, `README.md`, `INSTALL.md`, `LICENSE`, `.gitignore`, CI workflow,
`config/config.template.yaml`, `templates/*`, `examples/*`, the whole
`hermes-job-drop/` skill payload (SKILL.md + 7 references), `install.sh` + `install.py`,
`scripts/audit_no_personal_data.py`, `scripts/config.py`, and `tests/test_audit.py` +
`tests/test_config.py`.

### Slice 2 — the engine: resume, cover letter, ledger, JD extraction, the skill's run path
Deliver: `scripts/profile.py`, `scripts/llm.py`, `scripts/field_matching.py`,
`scripts/build_resume.py`, `scripts/build_cover_letter.py`, `scripts/jd_extract.py`,
`scripts/ledger.py`, the remaining tests, and the SKILL.md update that binds the engine to
the doctrine (with the exact commands).

### Slice 3 — OPTIONAL, only if Slice 2 lands green and time allows
`scripts/chrome_cdp.py` fallback driver + a real end-to-end run against a scratch ATS.

---

## 9. Acceptance criteria

### Slice 1
- [ ] `python3 scripts/audit_no_personal_data.py` exits 0 on the repo, and **fails** (non-zero)
      on a deliberately planted personal-data fixture in a temp copy (email, phone, address,
      tracked `.env`, tracked binary) — a test proves the detector actually detects.
- [ ] `tests/test_audit.py` passes: the fixture-based detection test, and a clean-tree test.
- [ ] `tests/test_config.py` passes: a valid config loads; a missing slot raises a named
      error; an unknown slot is reported; `command:` overrides `model` for that slot; a slot
      with no key and no ambient env reports "unresolved key" without printing a value.
- [ ] `install.sh` runs on a clean machine: creates `~/.hermes/jobdrop/` with the config
      template, profile template, templates, and an empty ledger; copies the skill to
      `~/.hermes/skills/hermes-job-drop/`; **does not** overwrite an existing user config
      without `--force`; prints the exact next steps.
- [ ] `install.py --doctor` reports per-slot resolved model/provider, key presence (boolean),
      and endpoint reachability (ok/fail) — and prints no secret value.
- [ ] `config/config.template.yaml` documents all six slots with a comment per slot naming
      what that slot is for.
- [ ] `templates/master_profile.template.yaml` is fully commented and validates against
      `scripts/profile.py`'s schema (once profile.py lands in Slice 2; in Slice 1 the
      template must at least be parseable YAML with every required key present).
- [ ] `examples/example_profile.yaml` contains no real person's data and uses `example.com`
      addresses.
- [ ] `SKILL.md` is a complete, self-contained process doctrine: how a drop is parsed, how
      the ledger dedupes, the run order, the submit rule, the park rule, the report format,
      and the "never fabricate" rule — with no reference to the source lane's private names.
- [ ] `README.md` gives a 5-step quickstart ending in "post a link and tag the bot".
- [ ] `git ls-files` contains no `.env`, no PDF, no `.db`, no absolute `/home/<name>/` path.
- [ ] Every file in the repo is either code, docs, a template, or a fictional example.

### Slice 2
- [ ] `build_resume.py` renders a **real PDF** from `examples/example_profile.yaml` +
      `templates/resume.html` via WeasyPrint, with zero personal data, and the PDF is
      non-trivial (>1 page or a full page of content). The test asserts the PDF is valid and
      contains the example persona's name.
- [ ] The resume build **fails loudly** when the profile is missing a required core role
      (test asserts a non-zero exit and a message naming the missing role) — never a silent
      omission.
- [ ] `build_resume.py --warn-unknown-tokens` reports unknown `{{TOKENS}}` in a user template
      and still builds.
- [ ] `build_cover_letter.py` produces a letter that passes the gates: paragraph count,
      word count band, no banned tool/agent names, no placeholders left unresolved, and no
      `{{` in the output. The gates are asserted by a test.
- [ ] `build_cover_letter.py` uses the `cover_letter` slot ONLY — a test proves a different
      slot's model is not called.
- [ ] `ledger.py` round-trips: insert a drop, re-insert the same URL → duplicate detected;
      record a submission → the report query returns it; states are constrained.
- [ ] `jd_extract.py` extracts the title/company/description text from a local HTML fixture
      (no network in tests) and from a real posting when run manually.
- [ ] `llm.py` resolves a slot to (model, provider, base_url, key) from config and resolves
      the key from `api_key_env`; it never reads a model from outside the config.
- [ ] `SKILL.md` contains the exact commands for every step (drop → dedupe → resolve → resume
      → letter → drive → record → report), and the report format names SUBMITTED vs PARKED.
- [ ] `pytest tests/ -q` is green.
- [ ] The audit still passes after all Slice 2 files land.
- [ ] A **synthetic persona end-to-end** passes: profile → PDF resume → cover letter →
      ledger rows, driven entirely by `examples/example_profile.yaml`.

---

## 10. Verification discipline for the builder

- Never assert a build succeeded from an exit code alone — read the output.
- The `cc` wrapper's `cost=` figure is not money spent on a subscription lane; never report
  it as spend.
- Do not claim a file exists because a tool said it wrote it — read it back.
- The audit must be run and shown green before any push to a public remote.
- If the source lane's live line and its remote diverge, that is the source repo's problem,
  not this repo's: this repo starts empty and imports nothing.
