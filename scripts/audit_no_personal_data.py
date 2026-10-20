#!/usr/bin/env python3
"""Fail if any git-tracked file looks like it carries personal data.

Scans `git ls-files` only (untracked and ignored files are the user's business).
Prints `path:line: [pattern] offending line` for every hit and exits 1 on any hit, 0 on a
clean tree. Stdlib only, so it runs anywhere CI or a contributor runs it:

    python3 scripts/audit_no_personal_data.py [--root REPO]

A gitignored `personal-denylist.local.txt` at the repo root adds extra banned strings (one per
line, `#` comments, case-insensitive) so a developer can ban e.g. their own employer names
without committing them.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

DENYLIST_NAME = "personal-denylist.local.txt"

BANNED_SUFFIXES = {".pem", ".key", ".p12", ".sqlite", ".sqlite3", ".db", ".pdf", ".docx"}
DATA_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "localhost"}
# A digit run with at most two separator chars between groups; >= 7 digits is phone-shaped.
PHONE_RE = re.compile(r"(?<![\w.])\+?\(?\d+(?:[ ().+-]{1,2}\d+)*(?![\w])")
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
IPV4_RE = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")
# NANP reserves the 555-01XX block for fiction, the phone equivalent of example.com.
FICTIONAL_PHONE_RE = re.compile(r"1?(?:\d{3})?55501\d\d")
LINKEDIN_RE = re.compile(r"linkedin\.com/in/([A-Za-z0-9_%-]+)", re.IGNORECASE)
HOME_RE = re.compile(r"(?:/home|/Users)/([^/\s'\"`]+)/")
ALLOWED_HOME_SEGMENTS = {"user", "runner", "ci"}
STREET_RE = re.compile(
    r"\b\d+ [A-Z][a-z]+ (?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Blvd|Boulevard|Way|Court|Ct)\b"
)
PLACEHOLDER_RE = re.compile(r"\{\{[^{}]*\}\}")


def banned_file_reason(path):
    p = Path(path)
    name = p.name.lower()
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "banned-file:.env"
    if name == DENYLIST_NAME:
        return "banned-file:local-denylist"
    if p.suffix.lower() in BANNED_SUFFIXES:
        return f"banned-file:{p.suffix.lower()}"
    if p.suffix.lower() in DATA_IMAGE_SUFFIXES and "data" in p.parts[:-1]:
        return "banned-file:image-in-data"
    return None


def line_hits(line, denylist):
    """Yield pattern names that fire on one line of text."""
    text = PLACEHOLDER_RE.sub("", line)  # {{TOKENS}} are always allowed
    for m in EMAIL_RE.finditer(text):
        domain = m.group(1).lower()
        if domain not in ALLOWED_EMAIL_DOMAINS and not any(
            domain.endswith("." + d) for d in ALLOWED_EMAIL_DOMAINS
        ):
            yield "email"
            break
    for m in PHONE_RE.finditer(text):
        run = m.group(0)
        digits = re.sub(r"\D", "", run)
        if len(digits) < 7:
            continue
        if ISO_DATE_RE.fullmatch(run) or IPV4_RE.fullmatch(run) or FICTIONAL_PHONE_RE.fullmatch(digits):
            continue
        yield "phone"
        break
    for m in LINKEDIN_RE.finditer(text):
        if not m.group(1).lower().startswith("example"):
            yield "linkedin-url"
            break
    for m in HOME_RE.finditer(text):
        seg = m.group(1)
        if seg not in ALLOWED_HOME_SEGMENTS and seg[0] not in "<{$~*":
            yield "home-path"
            break
    if STREET_RE.search(text):
        yield "street-address"
    low = line.lower()
    for term in denylist:
        if term in low:
            yield "denylist"
            break


def load_denylist(root):
    f = root / DENYLIST_NAME
    if not f.is_file():
        return None
    terms = []
    for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#"):
            terms.append(raw.lower())
    return terms


def tracked_files(root):
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True
    ).stdout
    return [p for p in out.decode("utf-8", "surrogateescape").split("\0") if p]


def audit(root):
    """Return a list of (path, line_no, pattern, line) hits; line_no 0 = whole-file hit."""
    root = Path(root).resolve()
    denylist = load_denylist(root)
    if denylist is None:
        print(f"notice: no {DENYLIST_NAME} found; running generic rules only", file=sys.stderr)
    denylist = denylist or []
    hits = []
    for rel in tracked_files(root):
        reason = banned_file_reason(rel)
        if reason:
            hits.append((rel, 0, reason, rel))
        low_rel = rel.lower()
        for term in denylist:
            if term in low_rel:
                hits.append((rel, 0, "denylist:path", rel))
                break
        path = root / rel
        if not path.is_file():
            continue  # deleted in the work tree but still in the index
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue  # binary; the banned-type rule above is what covers binaries
        for no, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            for pattern in line_hits(line, denylist):
                hits.append((rel, no, pattern, line.strip()))
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".", help="repository to audit (default: current dir)")
    args = ap.parse_args(argv)
    try:
        hits = audit(args.root)
    except subprocess.CalledProcessError as e:
        print(f"error: git ls-files failed in {args.root}: {e.stderr.decode().strip()}", file=sys.stderr)
        return 2
    for rel, no, pattern, line in hits:
        print(f"{rel}:{no}: [{pattern}] {line[:200]}")
    if hits:
        print(f"\nFAIL: {len(hits)} personal-data hit(s). Remove them (or untrack the file).")
        return 1
    print("OK: no personal-data patterns in tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
