#!/usr/bin/env python3
"""The submission ledger: SQLite at ~/.hermes/jobdrop/ledger.db. The record of every drop.

    python3 scripts/ledger.py key URL                         # the dedupe key for a URL
    python3 scripts/ledger.py add URL [--note TEXT] [--profile P]
    python3 scripts/ledger.py update ID [--company C] [--title T] [--profile P]
    python3 scripts/ledger.py state ID STATE [--detail TEXT]
    python3 scripts/ledger.py submit ID --job-url U --ats A --resume R [--cover-letter L]
                              --confirmation-text T [--confirmation-url U] --method M
    python3 scripts/ledger.py show ID                         # readback row + events, JSON
    python3 scripts/ledger.py report ID                       # the Discord report, from the row

Every command prints JSON (except `report`, which prints the report text). Reports are built
from the row as read back, never from what the caller believes happened.
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile as prof  # noqa: E402

DEFAULT_DB = Path("~/.hermes/jobdrop/ledger.db")
STATES = ("received", "resolving", "documents_ready", "filling", "submitted", "parked",
          "failed", "duplicate")
RESUMABLE = ("parked", "failed")
TRACKING_PARAMS = {"gclid", "fbclid", "ref", "source", "src", "lever-source", "gh_src"}

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS drops (
  id          INTEGER PRIMARY KEY,
  url         TEXT NOT NULL,
  url_key     TEXT NOT NULL UNIQUE,
  note        TEXT,
  company     TEXT,
  title       TEXT,
  state       TEXT NOT NULL DEFAULT 'received' CHECK (state IN ({", ".join(f"'{s}'" for s in STATES)})),
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
  method             TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id          INTEGER PRIMARY KEY,
  drop_id     INTEGER NOT NULL REFERENCES drops(id),
  event       TEXT NOT NULL,
  detail      TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class LedgerError(Exception):
    pass


def url_key(url):
    """Normalized dedupe key: same posting → same key, whatever wrapper or tracking it came in."""
    url = url.strip().strip("<>")
    parts = urlsplit(url if "://" in url else "https://" + url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    if parts.port:
        host += f":{parts.port}"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    path = re.sub(r"/+$", "", parts.path)
    path = re.sub(r"/(apply|application)$", "", path)  # the form page is the same posting
    gh = dict(query).get("gh_jid")
    if gh:  # a careers page embedding a Greenhouse posting is keyed by the posting id
        return f"greenhouse:{gh}"
    gh_path = re.match(r"(?:job-)?boards\.greenhouse\.io$", host) and re.search(r"/jobs/(\d+)", path)
    if gh_path:
        return f"greenhouse:{gh_path.group(1)}"
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


def connect(path=None):
    path = Path(path or DEFAULT_DB).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def event(conn, drop_id, name, detail=None):
    conn.execute("INSERT INTO events (drop_id, event, detail) VALUES (?, ?, ?)", (drop_id, name, detail))


def get_drop(conn, drop_id):
    row = conn.execute("SELECT * FROM drops WHERE id = ?", (drop_id,)).fetchone()
    if row is None:
        raise LedgerError(f"no drop #{drop_id}")
    return dict(row)


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def already_applied_match(entries, url=None, company=None, title=None):
    """The `already_applied` entry this drop matches (by URL, or by company + title), or None."""
    for entry in entries or []:
        e = str(entry).strip()
        if not e:
            continue
        if re.match(r"(https?://|www\.)", e, re.I):
            if url and url_key(e) == url_key(url):
                return e
        elif company and title and _norm(company) in _norm(e) and _norm(title) in _norm(e):
            return e
    return None


def add_drop(conn, url, note=None, already_applied=None):
    """Insert a drop, or detect it is one we already have. Returns {id, state, action}.

    action: 'new' | 'duplicate' (active/done row exists — no second application)
            | 'resumed' (a parked/failed row is picked back up) | 'already_applied'.
    """
    key = url_key(url)
    with conn:
        row = conn.execute("SELECT * FROM drops WHERE url_key = ?", (key,)).fetchone()
        if row:
            if row["state"] in RESUMABLE:
                event(conn, row["id"], "resumed", note)
                conn.execute("UPDATE drops SET note = COALESCE(?, note), updated_at = datetime('now') "
                             "WHERE id = ?", (note, row["id"]))
                return {"id": row["id"], "state": row["state"], "action": "resumed", "url_key": key}
            event(conn, row["id"], "redrop", url)
            return {"id": row["id"], "state": row["state"], "action": "duplicate", "url_key": key}
        match = already_applied_match(already_applied, url=url)
        state = "duplicate" if match else "received"
        cur = conn.execute("INSERT INTO drops (url, url_key, note, state) VALUES (?, ?, ?, ?)",
                           (url, key, note, state))
        event(conn, cur.lastrowid, state, f"already_applied: {match}" if match else note)
        return {"id": cur.lastrowid, "state": state, "url_key": key,
                "action": "already_applied" if match else "new"}


def set_state(conn, drop_id, state, detail=None):
    if state not in STATES:
        raise LedgerError(f"unknown state {state!r} (valid: {', '.join(STATES)})")
    if state == "submitted":
        raise LedgerError("use `submit` to mark a drop submitted — it requires the confirmation")
    with conn:
        get_drop(conn, drop_id)
        conn.execute("UPDATE drops SET state = ?, updated_at = datetime('now') WHERE id = ?", (state, drop_id))
        event(conn, drop_id, state, detail)
    return get_drop(conn, drop_id)


def update_drop(conn, drop_id, company=None, title=None, already_applied=None):
    """Set company/title once resolved; a match against `already_applied` marks it duplicate."""
    with conn:
        get_drop(conn, drop_id)
        conn.execute("UPDATE drops SET company = COALESCE(?, company), title = COALESCE(?, title), "
                     "updated_at = datetime('now') WHERE id = ?", (company, title, drop_id))
    d = get_drop(conn, drop_id)
    match = already_applied_match(already_applied, company=d["company"], title=d["title"])
    if match:
        d = set_state(conn, drop_id, "duplicate", f"already_applied: {match}")
    return d


def record_submission(conn, drop_id, *, job_url, ats=None, resume_path=None, cover_letter_path=None,
                      confirmation_url=None, confirmation_text=None, method=None):
    """A submission needs evidence: no confirmation text and no confirmation URL → refused."""
    if not (confirmation_text or "").strip() and not (confirmation_url or "").strip():
        raise LedgerError("no confirmation text or URL: that is not a submission. Re-check the page.")
    with conn:
        get_drop(conn, drop_id)
        conn.execute(
            "INSERT INTO submissions (drop_id, ats, job_url, resume_path, cover_letter_path, "
            "confirmation_url, confirmation_text, method) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (drop_id, ats, job_url, resume_path, cover_letter_path, confirmation_url,
             confirmation_text, method))
        conn.execute("UPDATE drops SET state = 'submitted', updated_at = datetime('now') WHERE id = ?",
                     (drop_id,))
        event(conn, drop_id, "submitted", (confirmation_text or confirmation_url)[:200])
    return readback(conn, drop_id)


def readback(conn, drop_id):
    """The row the report is built from: drop + latest submission + events."""
    row = conn.execute(
        "SELECT d.id, d.url, d.state, d.company, d.title, d.note, d.created_at, d.updated_at, "
        "s.ats, s.job_url, s.resume_path, s.cover_letter_path, s.confirmation_text, "
        "s.confirmation_url, s.submitted_at, s.method "
        "FROM drops d LEFT JOIN submissions s ON s.drop_id = d.id WHERE d.id = ? "
        "ORDER BY s.id DESC LIMIT 1", (drop_id,)).fetchone()
    if row is None:
        raise LedgerError(f"no drop #{drop_id}")
    out = dict(row)
    out["events"] = [dict(e) for e in conn.execute(
        "SELECT event, detail, created_at FROM events WHERE drop_id = ? ORDER BY id", (drop_id,))]
    return out


def _last_detail(row, name):
    for e in reversed(row["events"]):
        if e["event"] == name:
            return e["detail"] or ""
    return ""


def report(row):
    """The Discord report for a readback row. SUBMITTED only with a confirmation on the row."""
    what = f"{row['title']} at {row['company']}" if row["title"] and row["company"] else row["url"]
    n = row["id"]
    state = row["state"]
    if state == "submitted" and (row["confirmation_text"] or row["confirmation_url"]):
        name = lambda p: Path(p).name if p else None  # noqa: E731
        conf = " ".join((row["confirmation_text"] or "").split())[:200]
        return (f"SUBMITTED — {what}\n"
                f"ATS: {row['ats'] or 'unknown'} · Drop #{n}\n"
                f"Resume: {name(row['resume_path']) or 'none'} · Cover letter: "
                f"{name(row['cover_letter_path']) or 'none (no field)'}\n"
                f"Confirmation: \"{conf}\"\n"
                f"Link: {row['confirmation_url'] or row['job_url']}")
    if state == "parked":
        d = _last_detail(row, "parked")
        label = re.search(r'label="([^"]*)"', d)
        req = re.search(r"required=(\w+)", d)
        opts = re.search(r"options=(\[.*\])", d)
        try:
            options = " | ".join(json.loads(opts.group(1))) if opts else ""
        except ValueError:
            options = opts.group(1)
        kept = re.search(r"form=(\S+)", d)
        return (f"PARKED — {what} (Drop #{n})\n"
                f"I need one answer from you that isn't in your profile:\n"
                f"  \"{label.group(1) if label else d}\"" + (" (required)" if req and req.group(1) == "yes" else "") +
                (f"\n  Options: {options}" if options else "") +
                f"\nReply with your answer and I'll finish and submit. The form is "
                f"{'still open' if kept and kept.group(1) == 'open' else 'will need refilling'}.")
    if state == "duplicate":
        why = _last_detail(row, "duplicate")
        return (f"DUPLICATE — {what} (Drop #{n}, state: {state})\n"
                f"Already {'in your already-applied list' if why.startswith('already_applied') else 'handled'}. "
                f"Not applying again.")
    if state == "failed":
        return (f"FAILED — {what} (Drop #{n})\nReason: {_last_detail(row, 'failed') or 'unknown'}\n"
                f"What I'd need: re-drop the link once the blocker is cleared")
    return f"IN PROGRESS — {what} (Drop #{n}, state: {state})"


def _already_applied(profile_path):
    if not profile_path:
        return None
    return prof.load_profile(profile_path).get("already_applied") or []


def main(argv=None):
    ap = argparse.ArgumentParser(description="hermes-job-drop submission ledger")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="ledger file (default: %(default)s)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("key"); p.add_argument("url")
    p = sub.add_parser("add"); p.add_argument("url"); p.add_argument("--note"); p.add_argument("--profile")
    p = sub.add_parser("update"); p.add_argument("id", type=int)
    p.add_argument("--company"); p.add_argument("--title"); p.add_argument("--profile")
    p = sub.add_parser("state"); p.add_argument("id", type=int); p.add_argument("state", choices=STATES)
    p.add_argument("--detail")
    p = sub.add_parser("submit"); p.add_argument("id", type=int)
    p.add_argument("--job-url", required=True); p.add_argument("--ats"); p.add_argument("--resume")
    p.add_argument("--cover-letter"); p.add_argument("--confirmation-url")
    p.add_argument("--confirmation-text"); p.add_argument("--method")
    for name in ("show", "report"):
        sub.add_parser(name).add_argument("id", type=int)
    args = ap.parse_args(argv)

    if args.cmd == "key":
        print(url_key(args.url))
        return 0
    try:
        conn = connect(args.db)
        if args.cmd == "add":
            out = add_drop(conn, args.url, args.note, _already_applied(args.profile))
        elif args.cmd == "update":
            out = update_drop(conn, args.id, args.company, args.title, _already_applied(args.profile))
        elif args.cmd == "state":
            out = set_state(conn, args.id, args.state, args.detail)
        elif args.cmd == "submit":
            out = record_submission(conn, args.id, job_url=args.job_url, ats=args.ats,
                                    resume_path=args.resume, cover_letter_path=args.cover_letter,
                                    confirmation_url=args.confirmation_url,
                                    confirmation_text=args.confirmation_text, method=args.method)
        elif args.cmd == "show":
            out = readback(conn, args.id)
        else:
            print(report(readback(conn, args.id)))
            return 0
    except (LedgerError, prof.ProfileError, sqlite3.Error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
