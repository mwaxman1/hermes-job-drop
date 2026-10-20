#!/usr/bin/env python3
"""Load and validate the verified profile (~/.hermes/jobdrop/profile.yaml).

The profile is the ONLY source of claims about the user. This module checks its shape (every
section present, right types) and offers the small helpers the builders share.

    python3 scripts/profile.py [--profile PATH]           # validate the schema
    python3 scripts/profile.py [--profile PATH] --check   # + ready to apply (name, email, a role)
"""
import argparse
import copy
import sys
from pathlib import Path

DEFAULT_PROFILE = Path("~/.hermes/jobdrop/profile.yaml")

CONTACT_KEYS = ("first_name", "last_name", "preferred_name", "email", "phone", "city", "state",
                "country", "postal_code", "work_authorization", "willing_to_relocate",
                "remote_preference")
ROLE_KEYS = ("employer", "title", "location", "start", "end", "core", "bullets")
EDU_KEYS = ("institution", "degree", "location", "end", "details")
CERT_KEYS = ("name", "issuer", "year")
LINK_KEYS = ("linkedin", "github", "portfolio", "other")
EEO_KEYS = ("gender", "race_ethnicity", "veteran_status", "disability_status")
ANSWER_KEYS = ("salary_expectation", "notice_period", "how_did_you_hear")


class ProfileError(Exception):
    """The profile is unusable. The message names every problem and the file."""


def skeleton():
    """An empty profile with every key the schema requires (mirrors the shipped template)."""
    return {
        "contact": {k: "" for k in CONTACT_KEYS},
        "summary": "",
        "headline": "",
        "experience": [],
        "education": [],
        "skills": [],
        "certifications": [],
        "links": {"linkedin": "", "github": "", "portfolio": "", "other": []},
        "answers": {**{k: "" for k in ANSWER_KEYS}, "eeo": {k: "" for k in EEO_KEYS}},
        "already_applied": [],
    }


def normalize(doc):
    """Fill every missing schema key with its empty value. Unknown keys are kept as-is."""
    out = copy.deepcopy(doc)
    for key, empty in skeleton().items():
        if out.get(key) is None:
            out[key] = empty
        elif isinstance(empty, dict) and isinstance(out[key], dict):
            for k, v in empty.items():
                if out[key].get(k) is None:
                    out[key][k] = v
            if key == "answers" and isinstance(out[key].get("eeo"), dict):
                for k in EEO_KEYS:
                    out[key]["eeo"].setdefault(k, "")
    return out


def _is_str(v):
    return isinstance(v, str) or v is None


def validate(doc):
    """Return a list of schema problems (empty list = valid). Empty values are allowed."""
    if not isinstance(doc, dict):
        return ["top level must be a mapping"]
    problems = []
    for key in ("contact", "summary", "experience", "education", "skills", "certifications", "links"):
        if key not in doc:
            problems.append(f"missing section `{key}`")
    contact = doc.get("contact") or {}
    if not isinstance(contact, dict):
        problems.append("`contact` must be a mapping")
        contact = {}
    for k in CONTACT_KEYS:
        if not _is_str(contact.get(k)):
            problems.append(f"contact.{k} must be text")
    for key in ("summary", "headline"):
        if not _is_str(doc.get(key)):
            problems.append(f"`{key}` must be text")

    def check_list(name, keys, list_keys=()):
        items = doc.get(name) or []
        if not isinstance(items, list):
            problems.append(f"`{name}` must be a list")
            return
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                problems.append(f"{name}[{i}] must be a mapping")
                continue
            for k in keys:
                v = item.get(k)
                if k in list_keys:
                    if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
                        problems.append(f"{name}[{i}].{k} must be a list of text")
                elif k == "core":
                    if v is not None and not isinstance(v, bool):
                        problems.append(f"{name}[{i}].core must be true or false")
                elif not (_is_str(v) or isinstance(v, int)):
                    problems.append(f"{name}[{i}].{k} must be text")

    check_list("experience", ROLE_KEYS, ("bullets",))
    check_list("education", EDU_KEYS, ("details",))
    check_list("certifications", CERT_KEYS)
    check_list("skills", ("group", "items"), ("items",))
    links = doc.get("links") or {}
    if not isinstance(links, dict):
        problems.append("`links` must be a mapping")
    elif links.get("other") is not None and not isinstance(links["other"], list):
        problems.append("links.other must be a list")
    return problems


def readiness(doc):
    """What is missing before the kit can apply anywhere (name, email, one role with bullets)."""
    c = doc.get("contact") or {}
    missing = [f"contact.{k}" for k in ("first_name", "last_name", "email") if not text(c.get(k))]
    roles = [r for r in doc.get("experience") or [] if text(r.get("employer")) and text(r.get("title"))]
    if not any(bullets(r) for r in roles):
        missing.append("experience (at least one role with employer, title and a bullet)")
    return missing


def load_profile(path=None):
    """Parse, validate and normalize a profile file. Raises ProfileError naming every problem."""
    path = Path(path or DEFAULT_PROFILE).expanduser()
    if not path.is_file():
        raise ProfileError(f"profile not found: {path}. Run ingest_profile.py on a folder of your "
                           f"resumes, or copy profile.template.yaml to profile.yaml and fill it in.")
    try:
        import yaml
    except ImportError:
        raise ProfileError("PyYAML is required to read the profile: python3 -m pip install --user pyyaml")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ProfileError(f"{path} is not valid YAML: {e}")
    problems = validate(doc)
    if problems:
        raise ProfileError(f"{path}: " + "; ".join(problems))
    return normalize(doc)


# ---- helpers shared by the builders ---------------------------------------------------------

def text(v):
    return "" if v is None else str(v).strip()


def bullets(role):
    return [text(b) for b in role.get("bullets") or [] if text(b)]


def first_name(doc):
    c = doc["contact"]
    return text(c.get("preferred_name")) or text(c.get("first_name"))


def full_name(doc):
    return " ".join(x for x in (first_name(doc), text(doc["contact"].get("last_name"))) if x)


def location(doc):
    c = doc["contact"]
    return ", ".join(x for x in (text(c.get("city")), text(c.get("state"))) if x)


def link_list(doc):
    links = doc.get("links") or {}
    out = [text(links.get(k)) for k in ("linkedin", "github", "portfolio")]
    out += [text(x) for x in links.get("other") or []]
    return [x for x in out if x]


def contact_line(doc):
    """email · phone · City, ST · links — only the parts present."""
    c = doc["contact"]
    parts = [text(c.get("email")), text(c.get("phone")), location(doc)] + [
        x.split("://", 1)[-1].removeprefix("www.").rstrip("/") for x in link_list(doc)]
    return " · ".join(p for p in parts if p)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate the hermes-job-drop profile.")
    ap.add_argument("--profile", default=str(DEFAULT_PROFILE), help="profile file (default: %(default)s)")
    ap.add_argument("--check", action="store_true", help="also require name, email and one role")
    args = ap.parse_args(argv)
    try:
        doc = load_profile(args.profile)
    except ProfileError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    roles = doc["experience"]
    print(f"profile ok: {full_name(doc) or '(no name)'} · {len(roles)} role(s), "
          f"{sum(1 for r in roles if r.get('core'))} core")
    if args.check:
        missing = readiness(doc)
        if missing:
            print("not ready to apply; fill in: " + ", ".join(missing), file=sys.stderr)
            return 1
        print("ready to apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
