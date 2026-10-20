# Troubleshooting

## Setup

| Symptom | Cause | Fix |
|---|---|---|
| `missing model slot(s): …` | A slot in `config.yaml` is absent | Add it; there is no default model |
| `slot X: \`model\` and \`provider\` required` | Slot present but blank (the shipped template is blank on purpose) | Fill `model` and `provider` |
| `unknown key(s) api_key` | A raw key was put in the config | Delete it; put the key in an env var and set `api_key_env` to that var's NAME |
| doctor: `key_present=False (VAR unresolved)` | The env var is not set in the environment Hermes runs in | Export it in the shell / service env that starts Hermes, then restart it |
| doctor: `endpoint=fail` | No network, wrong `base_url`, local server not running | Check the URL; for local servers start them first |
| `PyYAML is required` | Python without PyYAML | `python3 -m pip install --user pyyaml` |
| The bot ignores the link | Bot not mentioned, or the skill not installed | Mention the bot in the same message; check `~/.hermes/skills/hermes-job-drop/SKILL.md` exists |

## Profile ingestion

| Symptom | Fix |
|---|---|
| `skipped: x.pdf (no PDF reader …)` | `python3 -m pip install --user pypdf` (or install poppler's `pdftotext`), re-run |
| `skipped: x.pdf (no extractable text — a scanned image?)` | The PDF is a picture of text. Export a text PDF/DOCX from the original, or fill those fields by hand |
| `profile.yaml exists and differs from this draft` | Your reviewed profile is protected. `--out -` to see the new draft, `--force` to replace it |
| A role's title and employer are swapped | Listed under "Check these" in the report — fix it in the draft; the order on resumes varies |
| Two values for the same contact field | Listed under "Check these"; the first file (alphabetical) won. Fix the draft if it is the wrong one |

## Documents

| Symptom | Fix |
|---|---|
| Resume build fails naming a core role | The profile marks it `core: true` but the role has no usable bullets, or tailoring tried to drop it. Fix the profile; never force the build past it |
| PDF has a date/path header | Missing `--no-pdf-header-footer`; re-render |
| Chrome render hangs | Must run under `timeout 60` with a throwaway `--user-data-dir`; if the PDF exists after the timeout it is usually complete — check the page count |
| Unknown token warning | A `{{TOKEN}}` in the user's template is misspelled or unsupported; fix the template |
| Letter fails a gate repeatedly | The profile lacks material that connects to the JD — say so in the report rather than padding |

## Forms

| Symptom | Fix |
|---|---|
| Upload "succeeds" but no filename appears | You targeted the button, not the file input; or the input is in a cross-origin iframe — open the iframe URL directly |
| Fields reset after upload | The parser overwrote them; refill from the profile after the upload |
| Submit does nothing | Scroll the whole form for inline validation errors; check for a captcha that appeared; check later wizard steps |
| "Something went wrong" after Submit | Wait, reload the confirmation/portal page — it may have gone through. Check the portal status before resubmitting to avoid a double application |
| Session expired mid-wizard | Sign back in; most account-based portals keep drafts. Re-verify every field |
| Login required and no credentials in the user's Chrome | Park and ask the user to sign in once in their Chrome, then re-drop |
| Same portal error three times | State `failed` with the error text; leave the tab open for the user |

## Ledger

| Symptom | Fix |
|---|---|
| Report and ledger disagree | The ledger wins. Re-read the row, report what it says, investigate the difference |
| A re-drop did nothing | Correct: the url_key already exists in an active/done state. The reply states that row's state |
| Need to retry a failed drop | Re-drop the same link: a `failed`/`parked` row resumes instead of duplicating |
