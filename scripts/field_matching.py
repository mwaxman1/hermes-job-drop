#!/usr/bin/env python3
"""Match a form field's label to a profile value, and a profile answer to the form's options.

Mechanics only: the browser model reads the form; this says where in the profile an answer
lives and which offered option means the same thing. An empty value means "not grounded" —
a required field then parks, an optional one stays blank. Nothing here invents a value.

    python3 scripts/field_matching.py "Legal first name" [--options "Yes|No"] [--profile P]

prints JSON: {"label", "key", "value", "grounded", "option"}.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile as prof  # noqa: E402

# (profile key, label pattern). Order matters: the first match wins, so specific rules
# (preferred name, LinkedIn URL) come before generic ones (name, URL).
RULES = [
    ("contact.preferred_name", r"preferred (first )?name|nick ?name|goes by"),
    ("contact.first_name", r"first name|given name|forename"),
    ("contact.last_name", r"last name|surname|family name"),
    ("full_name", r"^(full |legal |your )?name$|full name|legal name|signature"),
    ("contact.email", r"e-?mail"),
    ("contact.phone", r"phone|mobile|cell|telephone"),
    ("links.linkedin", r"linked ?in"),
    ("links.github", r"git ?hub"),
    ("links.portfolio", r"portfolio|personal (web)?site|website|blog|url"),
    ("contact.postal_code", r"zip|postal|post code"),
    ("contact.city", r"\bcity\b|town"),
    ("contact.state", r"\bstate\b|province|region"),
    ("contact.country", r"country"),
    ("location", r"location|where (are you|do you live)|based"),
    ("contact.work_authorization", r"authori[sz]|sponsor|visa|right to work|eligible to work|work permit"),
    ("contact.willing_to_relocate", r"relocat"),
    ("contact.remote_preference", r"remote|hybrid|on-?site|in office|work arrangement"),
    ("answers.salary_expectation", r"salary|compensation|pay expectation|desired pay"),
    ("answers.notice_period", r"notice period|start date|when can you start|availability"),
    ("answers.how_did_you_hear", r"how did you (hear|find|learn)|where did you (hear|find)|source"),
    ("answers.eeo.gender", r"gender|\bsex\b"),
    ("answers.eeo.race_ethnicity", r"race|ethnic|hispanic|latino"),
    ("answers.eeo.veteran_status", r"veteran|military"),
    ("answers.eeo.disability_status", r"disabilit"),
    ("current_employer", r"current (company|employer)|present employer|most recent (company|employer)"),
    ("current_title", r"current (job )?title|current (role|position)|most recent (title|role)"),
    ("headline", r"headline"),
    ("education.institution", r"school|university|college|institution"),
    ("education.degree", r"degree|qualification"),
    ("education.end", r"graduat"),
]
_COMPILED = [(k, re.compile(p, re.I)) for k, p in RULES]

DECLINE_RE = re.compile(r"decline|prefer not|don.?t wish|do not wish|not (to )?(say|answer|disclose)|rather not", re.I)


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def match_field(label):
    """The profile key a label asks for, or None (then the agent decides or parks)."""
    label = " ".join(str(label).replace("*", " ").split())
    for key, rx in _COMPILED:
        if rx.search(label):
            return key
    return None


def _current_role(doc):
    for r in doc["experience"]:
        if prof.text(r.get("end")).lower() in ("present", "current", "now", ""):
            return r
    return {}


def value_for(key, doc):
    """The profile's value for a key from match_field, '' when the profile does not have it."""
    t = prof.text
    if key is None:
        return ""
    if key == "full_name":
        return prof.full_name(doc)
    if key == "location":
        return ", ".join(x for x in (prof.location(doc), t(doc["contact"].get("country"))) if x)
    if key == "current_employer":
        return t(_current_role(doc).get("employer"))
    if key == "current_title":
        return t(_current_role(doc).get("title"))
    if key.startswith("education."):
        edu = doc["education"][0] if doc["education"] else {}
        return t(edu.get(key.split(".", 1)[1]))
    node = doc
    for part in key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return t(node)


def match_option(answer, options):
    """The one option meaning the same as `answer`, or None (ambiguous or no match → park)."""
    a = norm(answer)
    if not a or not options:
        return None
    exact = [o for o in options if norm(o) == a]
    if len(exact) == 1:
        return exact[0]
    if a == "decline":
        hits = [o for o in options if DECLINE_RE.search(str(o))]
        return hits[0] if len(hits) == 1 else None
    first = a.split()[0]
    if first in ("yes", "no"):
        hits = [o for o in options if norm(o).split()[:1] == [first]]
        return hits[0] if len(hits) == 1 else None
    # containment either way ("Remote" ↔ "Remote (US)"), but only if exactly one option fits
    hits = [o for o in options if norm(o) and (norm(o) in a or a in norm(o))]
    return hits[0] if len(hits) == 1 else None


def resolve(label, doc, options=None):
    key = match_field(label)
    value = value_for(key, doc)
    out = {"label": label, "key": key, "value": value, "grounded": bool(value)}
    if options:
        out["option"] = match_option(value, options) if value else None
        out["grounded"] = out["option"] is not None
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Map a form label (and options) to the profile.")
    ap.add_argument("label")
    ap.add_argument("--options", help="the form's options, separated by |")
    ap.add_argument("--profile", default=str(prof.DEFAULT_PROFILE))
    args = ap.parse_args(argv)
    try:
        doc = prof.load_profile(args.profile)
    except prof.ProfileError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    opts = [o.strip() for o in args.options.split("|")] if args.options else None
    print(json.dumps(resolve(args.label, doc, opts), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
