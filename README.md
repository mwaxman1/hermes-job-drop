# hermes-job-drop

Post a job link in Discord, tag your Hermes bot, and get a real, submitted application back:
a tailored resume and cover letter built only from your own verified profile, the form filled
and submitted in **your own** signed-in Chrome, and the result recorded in a local ledger.

- **Your models.** Six slots (vision, tooling, browser, python, resume, cover letter) — you
  pick the model and provider for each. There is no default model.
- **Your material.** Point the kit at the folder where your resumes already live. It drafts
  your profile from them; you review it once.
- **Never fabricates.** Every claim comes from your profile. If a form asks something only you
  can answer, the application **parks** and the bot asks you in Discord. Parking is a correct
  outcome.
- **Submits by default.** A filled form left for you to click is not a finished run.
- **Local and private.** Your profile, templates, documents and ledger live in
  `~/.hermes/jobdrop/`, never in this repo. CI fails if personal data is ever committed.

## Requirements

- [Hermes](https://github.com/NousResearch/hermes-agent) with its Discord gateway already set
  up (the kit adds no new bot or token)
- Google Chrome (or Chromium) — drives the forms and renders the PDFs
- Python 3.9+ with PyYAML (`python3 -m pip install --user pyyaml`)
- An API key for whichever model providers you choose (or a local model server)

## Quickstart (5 steps)

1. **Install.**
   ```bash
   git clone https://github.com/<you>/hermes-job-drop.git
   cd hermes-job-drop && bash install.sh
   ```
2. **Point it at your resumes.** Give it the folder where your resumes and documents already
   live; it drafts `~/.hermes/jobdrop/profile.yaml` and lists anything it could not find.
   ```bash
   python3 ~/.hermes/skills/hermes-job-drop/scripts/ingest_profile.py ~/path/to/your-resumes
   ```
   Review the draft once. It becomes the only source of truth for every application.
3. **Pick your models.** Edit `~/.hermes/jobdrop/config.yaml` — one model + provider per slot
   (see [`examples/example_config.yaml`](examples/example_config.yaml)) — and export the API
   key env vars it names.
4. **Check.**
   ```bash
   python3 ~/.hermes/skills/hermes-job-drop/scripts/config.py --doctor
   ```
   Every slot should show `key_present=True` and `endpoint=ok`.
5. **Post a job link in Discord and tag the bot.** It replies with **SUBMITTED** (what went
   to whom, with which documents) or **PARKED** (the one question it needs you to answer).

Details, model picking and troubleshooting: [INSTALL.md](INSTALL.md).

## What's in the box

| Path | What |
|---|---|
| `hermes-job-drop/` | The Hermes skill: `SKILL.md` (the procedure) + `references/` (ATS shapes, grounding, captchas, letter gates, resume builder, recording, troubleshooting) |
| `scripts/` | The engine (config + model slots, privacy audit; resume/letter/ledger engine) |
| `config/config.template.yaml` | The six model slots, documented |
| `templates/` | Profile schema, resume HTML template, cover-letter template — copied to `~/.hermes/jobdrop/` for you to edit |
| `examples/` | A synthetic persona and a filled-in config to try things with |
| `install.sh` / `install.py` | The installer (`--doctor`, `--force`, `--audit-user-data`) |

## Status

The kit (skill doctrine, templates, config, installer, privacy audit) is in place. The engine
scripts for profile ingestion, resume/letter building and the ledger are landing next; until
then the skill performs those steps by hand following its references, and the installer tells
you how to create your profile manually.

## License

MIT — see [LICENSE](LICENSE).
