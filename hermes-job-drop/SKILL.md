---
name: hermes-job-drop
description: Turn a job link posted in Discord (with the bot mentioned) into a real, submitted application — tailored resume, cover letter, form filled and submitted in the user's own Chrome, recorded in a local ledger. Parks honestly when only the user can answer.
version: 0.2.0
---

# hermes-job-drop

You are the process authority for one job drop. The user posted a job link in Discord and
mentioned the bot. Your job: apply to that job for them, end to end, and report back from the
ledger. This file is the whole procedure. The `references/` files hold the detail; read the
one named at each step when you reach it.

## Where things live

| What | Path |
|---|---|
| Model slots (which model does what) | `~/.hermes/jobdrop/config.yaml` |
| Verified profile — the ONLY source of claims about the user | `~/.hermes/jobdrop/profile.yaml` |
| Resume / cover-letter templates | `~/.hermes/jobdrop/templates/resume.html`, `cover_letter.md` |
| Ledger (SQLite) | `~/.hermes/jobdrop/ledger.db` |
| Per-application output (PDFs, evidence) | `~/.hermes/jobdrop/applications/<drop_id>/` |
| Engine scripts | `~/.hermes/skills/hermes-job-drop/scripts/` |

Below, `$KIT` means `~/.hermes/skills/hermes-job-drop` and `$JD` means `~/.hermes/jobdrop`.

Every step below gives the exact command. Run them as written (they print JSON or one clear
line) and read the output before moving on. The scripts enforce the doctrine — a non-zero exit
means stop and look, never "try something else that gets past it". If a script is missing,
do that step by hand exactly as its reference describes.

## The rules (read these first, they override everything below)

1. **Never fabricate.** Every claim, answer, date, credential, EEO answer, referral source and
   contact detail comes from `profile.yaml` or from the user in this conversation. If it is not
   there, you do not have it. You never "reasonably infer" an answer. → `references/answer-grounding.md`
2. **Submit is the default.** Open the form, fill it, get through the captcha, click Submit,
   confirm it went through, record it, move on. A filled form left for the user to click is
   NOT a finished run.
3. **Parking is a correct outcome.** When the only thing left is an answer only the user can
   give, stop, do not submit, record the park with the field's verbatim label and the form's
   real options, and ask. That is success at honesty, not a failure.
4. **The ledger is the record.** Report state by reading the ledger row, never from memory or a
   log line. If what you are about to say disagrees with the row, the row wins — fix the row
   or fix your report.
5. **Vision first.** Read the form from a screenshot + the page structure and decide what to do.
   Do not write a selector-based driver for a new portal. Python is for mechanics (uploads,
   files, ledger writes), never for perception.
6. **One application at a time, in the user's own signed-in Chrome.** Never a throwaway
   profile for a form. Never close or reuse a tab you did not open in this run.
7. **No purchases, no sends, no contracts.** You may submit job applications — that is the
   point. You may NOT pay for anything, accept paid upgrades ("boost your application"),
   sign agreements or e-signature documents, send messages or emails to anyone, or post
   anything publicly without the user explicitly confirming in Discord first. If a flow
   reaches any of these, stop at that screen and ask. This gate has no exceptions.
8. **Use the configured model per job.** Each concern uses its slot from `config.yaml`
   (`vision`, `tooling`, `browser`, `python`, `resume`, `cover_letter`). There is no default
   model; if a slot is missing, stop and tell the user which slot to fill in.

## Preflight (once per session)

```bash
python3 $KIT/scripts/config.py --doctor
python3 $KIT/scripts/profile.py --check
```

The doctor must show every slot with its model/provider, `key_present=True` (or "not
required"), and `endpoint=ok`. `profile.py --check` must print `ready to apply` (a name, an
email and one role with bullets). If either fails, reply with its output (it never contains
secrets) and stop. No profile yet → tell the user to run
`python3 $KIT/scripts/ingest_profile.py <folder of their resumes>` and review the draft.

## The run

Each step names the ledger state it leaves behind. States:
`received → resolving → documents_ready → filling → submitted | parked | failed`, plus
`duplicate`. Every `ledger.py` call that changes state also writes the `events` row.
→ `references/submission-recording.md`

### 1. Parse the drop  → state `received`

- Extract every `http(s)://` URL from the message. Strip surrounding `<>`, trailing
  punctuation, and Discord's link-preview wrappers.
- The **note** is any remaining text on the message after removing the URLs and the bot
  mention (e.g. "referral from a former colleague — mention it" or "remote only"). Keep it
  verbatim. A note is an instruction from the user and outranks inference, but it is NOT a
  source of facts unless it states one plainly.
- No URL in the message → reply "I didn't find a job link in that message" and stop.
- Several URLs → handle them **one at a time**, in the order posted, each as its own drop.
- A URL that is clearly not a job posting (a company homepage, a news article) → reply asking
  which role they meant; do not guess.

### 2. Dedupe  → `duplicate`, or continue

```bash
python3 $KIT/scripts/ledger.py add "$URL" --note "$NOTE" --profile $JD/profile.yaml
```

It normalizes the URL to a `url_key` (case, `www.`, fragments, tracking params, `/apply` and
`/application` sub-paths, Greenhouse `gh_jid`) and prints `{"id", "state", "action"}`. Set
`DROP=<id>` and `APP=$JD/applications/$DROP`, then by `action`:

- `new` → continue at step 3.
- `duplicate` → the posting is already active or done. **No second application.** Reply with
  `python3 $KIT/scripts/ledger.py report $DROP` and stop.
- `already_applied` → the URL is in the profile's `already_applied` list. Reply with the
  report and stop.
- `resumed` → a `parked`/`failed` drop is being picked back up (usually the user is
  re-dropping with the missing answer). Read `python3 $KIT/scripts/ledger.py show $DROP`
  and continue from the step its events show; reuse the files already in `$APP`.

### 3. Resolve the job  → `resolving`

```bash
python3 $KIT/scripts/ledger.py state $DROP resolving
mkdir -p "$APP"
python3 $KIT/scripts/jd_extract.py "$URL" --out "$APP/jd.json"
```

`jd.json` holds `title`, `company`, `location`, `description`, `ats`, `apply_url` (the page
that really holds the form) and `closed`. If the fetch fails or the description is empty
(a JavaScript-only page), open the posting in Chrome, save the page HTML to
`$APP/posting.html`, and run `jd_extract.py "$URL" --html "$APP/posting.html" --out "$APP/jd.json"`.
→ `references/ats-form-shapes.md` for how to recognize each ATS and where its form lives.

- `closed: true` (or HTTP 404) → `ledger.py state $DROP failed --detail "posting closed"`,
  report, stop.
- Otherwise record what it is:

```bash
python3 $KIT/scripts/ledger.py update $DROP --company "<company>" --title "<title>" --profile $JD/profile.yaml
```

  If that returns `"state": "duplicate"`, the company + role is in `already_applied`: report, stop.

### 4. Build the resume

```bash
python3 $KIT/scripts/build_resume.py --jd "$APP/jd.json" --out "$APP/resume.pdf"
```

The `resume` slot picks which **verified** bullets to show and in what order; the builder
refuses anything else (no rewritten bullet, no added claim, no dropped `core: true` role).
It writes `$APP/resume.html` and renders `$APP/resume.pdf` with Chrome. A non-zero exit
names the problem (e.g. a core role with no bullets): record
`ledger.py state $DROP failed --detail "<the error line>"`, report, and tell the user what to
fix in the profile. Never work around it. → `references/resume-builder.md`

**Visual gate** — the first run after the user's template or profile changes: rasterize and
look at the page before uploading anything.

```bash
pdftoppm -r 110 -png "$APP/resume.pdf" "$APP/page"    # then open page-1.png and LOOK at it
```

No `pdftoppm`? Open `$APP/resume.html` in Chrome and screenshot it instead.

### 5. Build the cover letter  → `documents_ready`

```bash
python3 $KIT/scripts/build_cover_letter.py --jd "$APP/jd.json" --note "$NOTE" \
  --out "$APP/cover_letter.md" --pdf "$APP/cover_letter.pdf"
python3 $KIT/scripts/ledger.py state $DROP documents_ready --detail "$APP/resume.pdf $APP/cover_letter.pdf"
```

Only the `cover_letter` slot writes the letter. It goes into the user's template and through
every gate in `references/cover-letter-gates.md`; a failing draft is sent back to the model
with the failures (up to 3 attempts). Exit `2` means it still failed — nothing was written and
the failures are listed. Then: if the form's cover letter is optional, apply without one and
record `ledger.py state $DROP documents_ready --detail "cover letter skipped: <failures>"`; if
it is required, `failed` with the first failure as the reason. Never write the letter
yourself and never upload a letter that failed a gate.

If the form has no cover-letter field, the letter is still useful for a free-text field it
fits; otherwise it is simply not uploaded (the report says "none (no field)").

### 6. Drive the form  → `filling`

```bash
python3 $KIT/scripts/ledger.py state $DROP filling --detail "ats=<ats> apply_url=<apply_url>"
```

In the user's own Chrome (the Hermes Chrome tools if present; otherwise the local CDP driver),
using the `browser` slot to read and act, `vision` for screenshots, `tooling`/`python` for
mechanics:

1. Open the `apply_url` in a **new tab you own**.
2. **Upload the resume first** (`$APP/resume.pdf` — many ATSs parse it and overwrite fields
   you typed before). Then `$APP/cover_letter.pdf` if there is a slot for it. Verify each
   filename shows on the page.
3. Fill every field from the profile. For any label you are unsure where to ground:

   ```bash
   python3 $KIT/scripts/field_matching.py "<verbatim label>" --options "<opt 1>|<opt 2>|<opt 3>"
   ```

   It prints the profile key, the value and the matching option; `"grounded": false` means
   the profile does not have it. Re-read anything the parser autofilled and correct it to
   match the profile exactly (parsers invent dates and split names wrongly).
4. Required question with no grounded answer → go to **Park** below. Optional question with no
   grounded answer → leave it blank.
5. Self-identification (EEO) questions: use the profile's `answers.eeo` values; `"decline"`
   means pick the form's decline option. Empty in the profile + required on the form → Park.
6. Captcha or verification step → `references/captcha-and-verification.md`. Solve it; do not
   refuse it. A code sent to the user's email or phone you cannot read → Park and ask for it.
7. Take a screenshot of the fully filled form, scrolled through, before submitting. Save it as
   `$APP/filled.png`.
8. **Click Submit.**
9. Confirm: a confirmation page, a "thank you / application received" message, or a status
   change in the portal. Capture the confirmation URL, the confirmation text verbatim, and a
   screenshot (`$APP/confirmation.png`). A click with no confirmation is NOT a submission —
   re-check the page for validation errors, fix, and resubmit.

### 7. Record, then report  → `submitted` | `parked` | `failed`

```bash
python3 $KIT/scripts/ledger.py submit $DROP --job-url "<apply_url>" --ats <ats> \
  --resume "$APP/resume.pdf" --cover-letter "$APP/cover_letter.pdf" \
  --confirmation-url "<url after submit>" --confirmation-text "<confirmation, verbatim>" \
  --method chrome-plugin            # or cdp | command
python3 $KIT/scripts/ledger.py report $DROP
```

`submit` refuses a submission with no confirmation text and no confirmation URL — that is
not a submission. Leave out `--cover-letter` if none was uploaded. `report` reads the row back
and prints the reply; post exactly that in the Discord thread.

A drop that cannot finish (portal error three times, login you cannot complete):

```bash
python3 $KIT/scripts/ledger.py state $DROP failed --detail "<one-line reason>"
python3 $KIT/scripts/ledger.py report $DROP
```

## Park (the honest outcome)

Park when, and only when, the form cannot be completed without an answer that is not in the
profile and that you must not invent (salary number, a yes/no about a past employer, a
required EEO answer the user left empty, a license number, an email/SMS code, "who referred
you", a question about their specific experience that the profile does not cover).

To park:
1. Do not submit. Do not pick a "safe" option. Do not close the tab you opened — leave the
   filled form in place if the portal keeps state; note whether it does.
2. Record it with the **verbatim field label**, whether it is required, the field type, the
   form's **actual options** (for a select/radio), and whether the form stays open:

   ```bash
   python3 $KIT/scripts/ledger.py state $DROP parked \
     --detail 'label="<verbatim label>" required=yes type=radio options=["Yes","No"] form=open'
   python3 $KIT/scripts/ledger.py report $DROP
   ```

   (`form=open` if the tab keeps the filled form, `form=lost` if it will need refilling.)
3. Post that PARKED report in the Discord thread.
4. When the user answers, write the answer into `profile.yaml` (`answers:` section) if it is a
   reusable fact, so the next form does not park on it again — then resume at step 6.

## Report format

Reply in the Discord thread of the drop with the output of `ledger.py report $DROP`, which
fills exactly one of these from the ledger row (and refuses SUBMITTED without a confirmation):

```
SUBMITTED — <title> at <company>
ATS: <ats> · Drop #<drop_id>
Resume: <resume filename> · Cover letter: <filename or "none (no field)">
Confirmation: "<confirmation text, verbatim, trimmed to one line>"
Link: <confirmation_url or job_url>
```

```
PARKED — <title> at <company> (Drop #<drop_id>)
I need one answer from you that isn't in your profile:
  "<verbatim field label>" (required)
  Options: <option 1> | <option 2> | <option 3>
Reply with your answer and I'll finish and submit. The form is <still open | will need refilling>.
```

```
DUPLICATE — <title or URL> (Drop #<drop_id>, state: <state>)
Already <submitted on <date> | in progress | in your already-applied list>. Not applying again.
```

```
FAILED — <title or URL> (Drop #<drop_id>)
Reason: <one line: posting closed / portal error after 3 tries / login required that I can't complete>
What I'd need: <one line>
```

Never write SUBMITTED unless the ledger row says `submitted` and has a confirmation. Never
pad a report with a summary of what the job is; the user posted it, they know.

## Reference index

- `references/ats-form-shapes.md` — per-ATS recognition, canonical URLs, form recipes, upload
  traps, confirmation routes.
- `references/answer-grounding.md` — where every answer may come from, and what parks.
- `references/captcha-and-verification.md` — solve-don't-refuse posture, codes, when to park.
- `references/resume-builder.md` — token contract, select-never-rewrite, Chrome rendering,
  the visual gate.
- `references/cover-letter-gates.md` — the gates every letter must pass.
- `references/submission-recording.md` — ledger schema, evidence, readback.
- `references/troubleshooting.md` — what to do when something specific goes wrong.
