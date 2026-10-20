# Cover-letter gates

Every cover letter (and every free-text "why us" answer) passes all of these before it is
uploaded or pasted. A letter that fails a gate is fixed or regenerated — never shipped as-is.

## Inputs

- `profile.yaml` — the only source of claims about the user.
- The job description (company, title, requirements, anything distinctive about the team).
- The drop's note, if any (e.g. "mention the referral from a former colleague").
- Optional: writing samples the user supplied, used **only** as a style reference.

The `cover_letter` slot produces the content as **JSON** with exactly the keys the template
needs, e.g.:

```json
{"GREETING": "...", "OPENING": "...", "BODY_PARA_1": "...", "BODY_PARA_2": "...",
 "BODY_PARA_3": "...", "CLOSING": "...", "SIGNATURE": "..."}
```

The template (`~/.hermes/jobdrop/templates/cover_letter.md`) owns the form. The kit fills
`FULL_NAME`, `CONTACT_LINE`, `DATE`, `COMPANY`, `ROLE_TITLE` itself from the profile and JD;
the model fills the rest. A token in the user's template that neither the kit nor the model
knows is a warning, not a crash. `BODY_PARA_3` may be empty; its blank line is then removed.

## The gates

1. **Length:** 250–400 words in the body (greeting through closing).
2. **Paragraphs:** 3–5 body paragraphs (opening + 1–3 body + closing).
3. **Grounding:** every claim about the user — role, employer, metric, skill, credential — is
   present in `profile.yaml`. Numbers are copied, not rounded up. No invented anecdotes.
4. **Specific to this job:** names the company and the exact role title; connects at least two
   of the user's verified points to stated requirements in the JD.
5. **Company correct:** the company name matches the posting; no other company's name appears
   except the user's own past employers.
6. **No placeholders:** no `{{`, no `}}`, no `[Company]`, `<role>`, `TODO`, `XX`, `lorem`.
7. **No tool or agent leakage:** no mention of AI, language models, automation, this kit, any
   model or provider name, or "as an assistant". The letter is the user's.
8. **Register:** professional, plain, first person. No exclamation marks. No clichés like "I am
   writing to express my interest", "perfect fit", "passionate about synergy", "hit the ground
   running". No flattery of the company beyond one specific, true sentence.
9. **No new commitments:** never states salary, start date, relocation, or availability unless
   the profile's `answers:` says so.
10. **Signature:** the user's name as in the profile (preferred name if set).

## How to check

Mechanical gates (1, 2, 5, 6, 7) are checked by counting and string search on the final text.
Gates 3 and 4 are checked by listing each claim in the letter next to the profile line it came
from; any claim without a line is removed. Do the check on the final rendered letter, not on
the model's JSON.
