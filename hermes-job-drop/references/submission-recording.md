# Submission recording — the ledger and the evidence

The ledger at `~/.hermes/jobdrop/ledger.db` is the record of what happened. Every report is
built by reading it. A run that says "submitted" while its row says otherwise is a bug.

## Schema

If the ledger engine script is installed it creates this for you; otherwise create it once:

```sql
CREATE TABLE IF NOT EXISTS drops (
  id          INTEGER PRIMARY KEY,
  url         TEXT NOT NULL,
  url_key     TEXT NOT NULL UNIQUE,
  note        TEXT,
  company     TEXT,
  title       TEXT,
  state       TEXT NOT NULL DEFAULT 'received' CHECK (state IN
              ('received','resolving','documents_ready','filling',
               'submitted','parked','failed','duplicate')),
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS submissions (
  id                 INTEGER PRIMARY KEY,
  drop_id            INTEGER NOT NULL REFERENCES drops(id),
  ats                TEXT,
  job_url            TEXT NOT NULL,
  resume_path        TEXT,
  cover_letter_path  TEXT,
  confirmation_url   TEXT,
  confirmation_text  TEXT,
  submitted_at       TEXT NOT NULL DEFAULT (datetime('now')),
  method             TEXT            -- 'chrome-plugin' | 'cdp' | 'command'
);
CREATE TABLE IF NOT EXISTS events (
  id          INTEGER PRIMARY KEY,
  drop_id     INTEGER NOT NULL REFERENCES drops(id),
  event       TEXT NOT NULL,
  detail      TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Use Python's built-in `sqlite3` module (`python3 -c "import sqlite3; ..."`) with **bound
parameters** (`?`), never string-formatted SQL — job titles contain quotes.

## State transitions

| From | To | When | Event row |
|---|---|---|---|
| (new) | `received` | drop parsed, url_key new | `received` + the note |
| (new) | `duplicate` | matches the profile's already-applied list | `duplicate` + what matched |
| `received` | `resolving` | fetching the posting | `resolving` |
| `resolving` | `documents_ready` | resume + letter built and gated | `documents_ready` + file paths |
| `documents_ready` | `filling` | form opened | `filling` + canonical apply URL, ATS |
| `filling` | `submitted` | confirmation captured | `submitted` + confirmation summary |
| any active | `parked` | needs an answer only the user has | `parked` + verbatim label, options |
| any active | `failed` | cannot proceed (closed posting, repeated portal error) | `failed` + reason |
| `parked`/`failed` | `resolving`/`filling` | user re-drops or answers | `resumed` |

Every state change also sets `updated_at = datetime('now')`.

## Evidence for a submission

Store in `~/.hermes/jobdrop/applications/<drop_id>/`:

- `resume.pdf`, `cover_letter.md`, `cover_letter.pdf` — exactly the files uploaded.
- `filled.png` — the filled form before Submit (more than one if the form scrolls).
- `confirmation.png` — the confirmation state.

And in the `submissions` row:

- `confirmation_url` — the URL shown after submit (or the posting URL if the page did not
  change).
- `confirmation_text` — the confirmation message **verbatim**, as shown. Not paraphrased.
- `ats`, `job_url`, `resume_path`, `cover_letter_path`, `method`.

No confirmation text and no confirmation URL → it is not a submission. Do not write a
`submissions` row; investigate the page instead (`troubleshooting.md`).

## Readback (mandatory)

After writing, read back:

```sql
SELECT d.id, d.state, d.company, d.title, s.confirmation_text, s.confirmation_url, s.submitted_at
FROM drops d LEFT JOIN submissions s ON s.drop_id = d.id
WHERE d.id = ?;
```

Build the Discord report from this result and nothing else. If the readback shows a state
you did not expect, report what the row says and investigate — do not overwrite it to match
your story.

## Parks

The `parked` event's `detail` must hold: the verbatim field label, whether it is required,
the field type, and the exact options offered (for selects/radios), e.g.

```
label="Are you legally authorized to work in Canada?" required=yes type=radio options=["Yes","No"]
```

That detail is what the PARKED report quotes back to the user.
