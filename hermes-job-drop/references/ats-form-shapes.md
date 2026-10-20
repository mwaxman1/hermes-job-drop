# ATS form shapes

How to recognize each applicant-tracking system, where its real form lives, how its form
behaves, and how it confirms a submission. These are **shapes and recipes**, not selectors:
read the actual page (screenshot + structure) every time, and use this file to know what to
expect and where the traps are. Portals change their markup; the shapes change slowly.

## General recipe (every ATS)

1. **Find the canonical apply URL.** Company career pages often embed the ATS in an iframe or
   wrap it in their own chrome. Prefer opening the ATS's own posting URL directly — fewer
   iframes, fewer cross-origin upload problems.
2. **Upload before typing.** Resume upload often triggers a parser that overwrites fields.
3. **Re-read every autofilled field** against `profile.yaml`. Fix names split wrong, dates
   guessed from text, phone numbers reformatted, and phantom "employers" invented from
   section headings.
4. **Scroll the whole form before submitting.** Required fields hide below the fold, inside
   collapsed sections, and on later wizard steps.
5. **Validation errors after Submit are normal.** Read them, fix the named fields, resubmit.
   Only a confirmation (page, message, or status) counts as submitted.
6. **Record the confirmation verbatim.** → `submission-recording.md`

## Recognition table

| ATS | URL shapes | Form location |
|---|---|---|
| Greenhouse | `boards.greenhouse.io/<org>/jobs/<id>`, `job-boards.greenhouse.io/<org>/jobs/<id>`, careers pages with `?gh_jid=<id>` | Same page as the posting, below the description (or behind an "Apply" button that scrolls to it) |
| Lever | `jobs.lever.co/<org>/<uuid>` | `jobs.lever.co/<org>/<uuid>/apply` |
| Ashby | `jobs.ashbyhq.com/<org>/<uuid>` | `…/<uuid>/application` (an "Application" tab) |
| Workday | `<tenant>.wd<N>.myworkdayjobs.com/<site>/job/<location>/<title>_<reqid>` | Multi-step wizard after "Apply" → account sign-in/creation |
| SmartRecruiters | `jobs.smartrecruiters.com/<org>/<id>` | "I'm interested" → one-page form |
| iCIMS | `careers-<org>.icims.com/jobs/<id>/<slug>/job` | Iframed, usually account-based, multi-step |
| Workable | `apply.workable.com/<org>/j/<id>/` | `…/j/<id>/apply/` |
| BambooHR | `<org>.bamboohr.com/careers/<id>` | Same page, "Apply for this job" expands the form |
| Jobvite | `jobs.jobvite.com/<org>/job/<id>` | `…/job/<id>/apply` |
| Oracle / Taleo / SuccessFactors | `*.taleo.net`, `*.oraclecloud.com/hcmUI/CandidateExperience`, `*.successfactors.com` | Account-based multi-step wizards |
| LinkedIn Easy Apply | `linkedin.com/jobs/view/<id>` with an "Easy Apply" button | Modal, multi-step, inside the user's logged-in LinkedIn |

When the posting is on a company site, look for these hosts in links, iframes, or the page
source to learn which ATS is underneath.

## Greenhouse

- **Shape:** single page. Standard block (first/last name, email, phone, location, resume,
  cover letter), then custom questions, then an optional voluntary self-identification block.
- **Uploads:** "Attach" opens a native file chooser bound to a hidden file input — upload to
  that input. "Enter manually" swaps in a text box; prefer the file. Some boards autofill
  from the resume; re-check after.
- **Location:** often an autocomplete — type, then pick a suggestion; a typed value with no
  picked suggestion can fail validation.
- **Custom questions:** selects are frequently custom dropdowns, not native `<select>`.
  Click, read the options from the opened list, click the exact option.
- **Verification:** newer boards may email a security code before accepting the submission.
  → `captcha-and-verification.md`
- **Confirmation:** a "Thank you for applying" page or panel; the URL often ends in
  `/confirmation`.

## Lever

- **Shape:** single page under `/apply`. Resume upload at the top, then contact fields, links
  (LinkedIn, GitHub, portfolio, other), "Additional information" free text, custom cards,
  then EEO.
- **Uploads:** resume upload parses and fills name/email/phone/company — verify every one.
- **Cover letter:** usually no file slot; "Additional information" is the place for the letter
  text if the user wants one included.
- **Captcha:** commonly an hCaptcha on submit.
- **Confirmation:** redirect to a `/thanks` page ("Application submitted").

## Ashby

- **Shape:** single-page React form on the Application tab. Optional "Autofill from resume".
- **Uploads:** drag-drop zone backed by a file input; after upload the filename appears in the
  zone — confirm it.
- **Fields:** yes/no questions are toggle buttons, not radios. Location may be an
  autocomplete.
- **Confirmation:** in-page success state ("Thanks for applying" / "Application submitted").
  There may be no URL change — capture the text and a screenshot.

## Workday

- **Shape:** a tenant-specific account (email + password) is required per company. Wizard
  steps typically: My Information → My Experience → Application Questions → Voluntary
  Disclosures → Self Identify → Review → Submit.
- **Account:** if the user has no account for this tenant, creating one is allowed (it is not
  a purchase or a contract), using the profile email. Store nothing; the password comes from
  the user's password manager in their Chrome, or the user is asked. An email verification
  link may be required → `captcha-and-verification.md`.
- **Uploads:** resume upload on My Experience parses into work-history entries, often wrongly
  (wrong dates, merged roles, phantom entries). Either delete and re-enter from the profile,
  or correct every entry. Do not leave parser inventions in place.
- **Traps:** "How did you hear about us" is a nested picker; date fields are segmented
  (MM / YYYY); "Previously worked here?" yes/no is required — answer only from the profile.
- **Confirmation:** after Submit, a confirmation message and the application appears under
  the candidate home with status "Submitted" / "In review". Capture both.

## SmartRecruiters

- **Shape:** one page after "I'm interested". Resume upload can autofill. Experience and
  education entries are editable cards.
- **Confirmation:** in-page "Application submitted" plus usually an email.

## iCIMS

- **Shape:** usually inside an iframe; often login/account first, then several steps
  (profile, documents, questions, EEO, signature-style "I certify" checkbox).
- **"I certify" checkbox:** certifying the application is accurate is part of applying and
  is allowed. A separate document to e-sign (offer, agreement, arbitration contract) is NOT —
  stop and ask (SKILL rule 7).
- **Confirmation:** a final "Thank you" step; capture it.

## Workable

- **Shape:** single page under `/apply/`, sections for personal info, profile (resume, cover
  letter, summary), details/questions.
- **Confirmation:** in-page success ("Application submitted" / "Thank you").

## BambooHR, Jobvite

- **Shape:** single page, conventional fields, native inputs mostly.
- **Confirmation:** in-page thank-you message.

## Oracle / Taleo / SuccessFactors

- **Shape:** account-based, long multi-step wizards, session timeouts. Save progress where the
  portal allows. Expect repeated questions across steps; answer each from the profile.
- **Confirmation:** a submission confirmation page and a status in the candidate portal.

## LinkedIn Easy Apply

- Runs in the user's logged-in LinkedIn. Multi-step modal: contact info (pre-filled from their
  LinkedIn — check it matches the profile), resume choice, questions, review.
- Numeric "years of experience with X" questions: answer only from the profile's dated roles
  and skills; if the profile cannot ground the number, park.
- Untick "Follow company" only if the user's profile says so — otherwise leave the default.
- Confirmation: "Your application was sent" dialog; capture it.

## Upload traps (all portals)

- The visible button is rarely the `<input type="file">`. Upload to the input element itself
  with the browser tool's file-upload action; do not type a path into a text box.
- Some zones accept only PDF/DOCX under a size limit (often 2–5 MB). The kit's PDFs are small;
  if rejected, read the message.
- After upload, confirm the filename (or a parsed preview) is visible. No visible filename =
  not uploaded.
- Cross-origin iframes can block uploads from the outer page: open the iframe's own URL in
  your tab and upload there.

## Confirmation routes (what counts as "submitted")

Any one of: a confirmation page/URL; an in-page success message naming the application; the
application listed with a submitted status in the portal. A spinner, a disabled button, or
a click with no visible change does **not** count — wait, re-read the page, and check for
errors before deciding.
