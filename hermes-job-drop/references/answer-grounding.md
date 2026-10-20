# Answer grounding — where every answer may come from

Every value you put into a form must trace to a source in this list. If it does not, you do
not have it.

## Allowed sources, in priority order

1. **What the user said in this conversation** — the drop's note, or an answer they gave to
   a PARKED question. (Write reusable answers back into `profile.yaml` → `answers:`.)
2. **`~/.hermes/jobdrop/profile.yaml`** — contact block, roles, education, skills,
   certifications, links, `answers:` (salary, notice period, how-did-you-hear, EEO choices),
   `already_applied`.
3. **The job posting itself** — only for facts about the job (company name, title, location,
   requirements), never for facts about the user.

Nothing else. Not the parsed resume a portal autofilled (it is a guess about the profile — fix
it to match). Not "what most candidates answer". Not a sensible default.

## Mapping questions to the profile

| Form asks | Ground in |
|---|---|
| Name, email, phone, city/state/country | `contact` |
| LinkedIn / GitHub / portfolio / website | `links` |
| Current company / title | the most recent `experience` entry with `end: present` |
| Years of experience (overall or in X) | arithmetic over dated `experience` entries; for a specific skill, only if roles/bullets name it — otherwise park |
| Degree, school, graduation year | `education` |
| Work authorization, sponsorship | `contact.work_authorization` — answer the exact question asked; if the stored text does not settle it (e.g. a different country), park |
| Relocation, remote/onsite | `contact.willing_to_relocate`, `contact.remote_preference` |
| Salary expectation | `answers.salary_expectation`; empty → park (if optional, leave blank) |
| Notice period / start date | `answers.notice_period` |
| How did you hear about us | `answers.how_did_you_hear`; if the note names a referral, that wins |
| Referred by / referrer name | only from the note or the user; never invented |
| EEO / self-identification | `answers.eeo.*`; `"decline"` = the form's decline option; empty + required → park; empty + optional → leave blank |
| "Why do you want to work here?" / short essays | composed from the profile + JD by the `cover_letter` slot, held to the cover-letter gates; no new claims |
| Anything about a specific past situation the profile does not record | park |

## Option matching

For selects and radios, pick the option whose meaning equals the profile answer. Equivalent
wording is fine ("Yes" ↔ "I am authorized"). If no option matches the meaning, or two do and
they differ in substance, park with the real options listed. Never pick the "closest" option
when it changes the meaning.

## Free-text short answers

Short answers are cover-letter-grade writing and follow the same gates: every claim must be a
verified bullet or profile fact, no invented metrics, no invented motivation stories, no tool
or agent names, no placeholders.

## What parks

A **required** field that cannot be grounded parks the application. An **optional** field that
cannot be grounded is left blank — that is not a park. Never fill a required field with
"N/A", "-", "0", or a made-up value to get past validation.
