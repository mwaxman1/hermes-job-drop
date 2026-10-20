---
name: hermes-job-drop
description: Turn a job link posted in Discord (with the bot mentioned) into a real, submitted application — tailored resume, cover letter, form filled and submitted in the user's own Chrome, recorded in a local ledger. Parks honestly when only the user can answer.
version: 0.1.0
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

If an engine script named in a step is not installed, do that step by hand exactly as its
reference describes. The doctrine is the same either way; scripts only make it faster.

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
```

Every slot must show its model/provider, `key_present=True` (or "not required"), and
`endpoint=ok`. If not, reply with the doctor output (it never contains secrets) and stop.
Also confirm `$JD/profile.yaml` exists and has at least a name, an email and one role. If it
does not, tell the user to run the profile ingestion step from the README and stop.

## The run

Each step names the ledger state it leaves behind. States:
`received → resolving → documents_ready → filling → submitted | parked | failed`, plus
`duplicate`. Write an `events` row at every transition. → `references/submission-recording.md`

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

Compute the **url_key**: lowercase scheme and host, drop `www.`, drop the `#fragment`, drop
tracking query params (`utm_*`, `gclid`, `fbclid`, `ref`, `source`, `src`, `lever-source`,
`gh_src`), drop a trailing `/`, and collapse ATS apply sub-paths to the posting
(`…/apply`, `…/application` → the posting URL; a careers page with `gh_jid=<id>` → that
Greenhouse posting). Then:

- url_key already in `drops` with state `received`, `resolving`, `documents_ready`, `filling`,
  `submitted` or `duplicate` → **no-op.** Add an `events` row (`event = 'redrop'`) to the
  existing drop and reply with that row's current state. Never a second application.
- url_key exists with state `parked` or `failed` → **resume that row** (the user is usually
  re-dropping with the missing answer). Do not insert a new row.
- The company + role (or the URL) matches an entry in the profile's `already_applied` list →
  insert the drop with state `duplicate`, reply saying so, stop.
- Otherwise insert a new `drops` row with state `received`.

### 3. Resolve the job  → `resolving`

Open the posting and extract: company, job title, location, the full description text, the
ATS family, and the **canonical apply URL** (the page that actually holds the form). Update
the drop's `company` and `title`. → `references/ats-form-shapes.md` for how to recognize each
ATS and where its form really lives.

If the posting is closed/expired/404 → state `failed`, detail "posting closed", report, stop.

### 4. Build the resume

From `profile.yaml` + the job description, using the `resume` slot. The JD may **select and
order** the user's verified bullets and trim the summary; it may never rewrite a bullet or add
a claim. Every role marked `core: true` must appear — if one cannot, the build fails loudly.
Render with the user's Chrome to `$JD/applications/<drop_id>/resume.pdf`.
→ `references/resume-builder.md`

### 5. Build the cover letter  → `documents_ready`

From `profile.yaml` + the JD (+ the note), using the `cover_letter` slot, into the user's
`cover_letter.md` template, through every gate in `references/cover-letter-gates.md`. A
letter that fails a gate is regenerated or fixed, never sent as-is. Write it as both `.md`
and `.pdf` beside the resume. If the form has no cover-letter field, build it anyway only if
there is a free-text field it would fit; otherwise skip it and note that in the events.

### 6. Drive the form  → `filling`

In the user's own Chrome (the Hermes Chrome tools if present; otherwise the local CDP driver),
using the `browser` slot to read and act, `vision` for screenshots, `tooling`/`python` for
mechanics:

1. Open the canonical apply URL in a **new tab you own**.
2. **Upload the resume first** (many ATSs parse it and overwrite fields you typed before).
   Then the cover letter if there is a slot for it. Verify each filename shows on the page.
3. Fill every field from the profile. Re-read anything the parser autofilled and correct it to
   match the profile exactly (parsers invent dates and split names wrongly).
4. Required question with no grounded answer → go to **Park** below. Optional question with no
   grounded answer → leave it blank.
5. Self-identification (EEO) questions: use the profile's `answers.eeo` values; `"decline"`
   means pick the form's decline option. Empty in the profile + required on the form → Park.
6. Captcha or verification step → `references/captcha-and-verification.md`. Solve it; do not
   refuse it. A code sent to the user's email or phone you cannot read → Park and ask for it.
7. Take a screenshot of the fully filled form, scrolled through, before submitting. Keep it as
   evidence in the application folder.
8. **Click Submit.**
9. Confirm: a confirmation page, a "thank you / application received" message, or a status
   change in the portal. Capture the confirmation URL, the confirmation text verbatim, and a
   screenshot. A click with no confirmation is NOT a submission — re-check the page for
   validation errors, fix, and resubmit.

### 7. Record, then report  → `submitted` | `parked` | `failed`

Write the `submissions` row (for submitted) and the final state, then **read the row back**
and build the report from what you read. → `references/submission-recording.md`

## Park (the honest outcome)

Park when, and only when, the form cannot be completed without an answer that is not in the
profile and that you must not invent (salary number, a yes/no about a past employer, a
required EEO answer the user left empty, a license number, an email/SMS code, "who referred
you", a question about their specific experience that the profile does not cover).

To park:
1. Do not submit. Do not pick a "safe" option. Do not close the tab you opened — leave the
   filled form in place if the portal keeps state; note whether it does.
2. Record state `parked` with the **verbatim field label**, whether it is required, and the
   form's **actual options** (for a select/radio) in the event detail.
3. Ask in the Discord thread using the PARKED report below.
4. When the user answers, write the answer into `profile.yaml` (`answers:` section) if it is a
   reusable fact, so the next form does not park on it again — then resume at step 6.

## Report format

Reply in the Discord thread of the drop. Use exactly one of these, filled from the ledger row.

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
