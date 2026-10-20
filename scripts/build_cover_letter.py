#!/usr/bin/env python3
"""Write a cover letter: profile + job description → the `cover_letter` slot → template → gates.

    python3 scripts/build_cover_letter.py --jd jd.json --out DIR/cover_letter.md [--pdf DIR/cover_letter.pdf]
        [--profile P] [--template T] [--note "referral from a former colleague"]
        [--company C] [--title T] [--style-sample FILE ...] [--content content.json] [--config C]

The template owns the FORM; the `cover_letter` slot supplies the CONTENT as JSON for the
template's tokens. The kit fills FULL_NAME, CONTACT_LINE, DATE, COMPANY, ROLE_TITLE itself.
Every letter passes the gates in references/cover-letter-gates.md before it is written; a
failing letter is regenerated (the failures are fed back), and after the last attempt the
build exits non-zero with the failures listed. No letter that fails a gate is ever written.

--content skips the model and gates a JSON file you (or the agent) wrote instead.
"""
import argparse
import datetime
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_resume  # noqa: E402
import config  # noqa: E402
import llm  # noqa: E402
import profile as prof  # noqa: E402

SLOT = "cover_letter"  # the only slot this script ever calls
KIT_TOKENS = ("FULL_NAME", "CONTACT_LINE", "DATE", "COMPANY", "ROLE_TITLE")
MODEL_TOKENS = ("GREETING", "OPENING", "BODY_PARA_1", "BODY_PARA_2", "BODY_PARA_3", "CLOSING", "SIGNATURE")
PARAGRAPH_TOKENS = ("OPENING", "BODY_PARA_1", "BODY_PARA_2", "BODY_PARA_3", "CLOSING")
OPTIONAL_TOKENS = ("BODY_PARA_2", "BODY_PARA_3")
TOKEN_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
WORDS = (250, 400)
PARAGRAPHS = (3, 5)

# Gate 7: nothing that betrays a tool wrote it. Configured model and provider names are added
# at runtime. A term the profile itself uses (e.g. "automated" in a verified bullet) is allowed.
LEAK_TERMS = [r"\bAI\b", r"artificial intelligence", r"language model", r"\bLLMs?\b", r"chat ?gpt",
              r"\bGPT\b", r"\bclaude\b", r"anthropic", r"openai", r"\bgemini\b", r"copilot", r"\bhermes\b",
              r"as an assistant", r"\bthis kit\b", r"job[- ]drop", r"\bautomation\b", r"\bbot\b"]
CLICHES = [r"writing to express my interest", r"perfect fit", r"synerg", r"hit the ground running",
           r"passionate about", r"dream (job|company)", r"team player", r"think outside the box",
           r"go-getter", r"\bguru\b", r"\bninja\b", r"rock ?star", r"to whom it may concern"]
PLACEHOLDER_RES = [r"\{\{", r"\}\}", r"\[[A-Z][A-Za-z ]*\]", r"<[a-z][a-z _]*>", r"\bTODO\b", r"\bTBD\b",
                   r"\bXX+\b", r"(?i:lorem|ipsum)"]


class GateError(Exception):
    def __init__(self, failures):
        self.failures = failures
        super().__init__("; ".join(failures))


def words(s):
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'’.-]*", s)


def paragraphs(s):
    return [p for p in re.split(r"\n\s*\n", s.strip()) if p.strip()]


def profile_text(doc):
    """Every string in the profile, lowercased — what a letter's claims may draw from."""
    out = []

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif v is not None:
            out.append(str(v))
    walk(doc)
    return "\n".join(out).lower()


def banned_terms(config_path):
    """Leak terms + the configured model and provider names (gate 7)."""
    terms = list(LEAK_TERMS)
    try:
        for s in config.load_config(config_path).values():
            for name in (s.model, s.provider):
                if name and len(name) > 2:
                    terms.append(re.escape(name))
    except config.ConfigError:
        pass
    return terms


def gate(content, letter, doc, jd, banned):
    """All mechanical gates on the model's content and the final rendered letter. Returns failures."""
    f = []
    body_text = "\n\n".join(content.get(k, "") for k in ("GREETING",) + PARAGRAPH_TOKENS if content.get(k))
    n_words = len(words(body_text))
    if not WORDS[0] <= n_words <= WORDS[1]:
        f.append(f"length: body is {n_words} words; must be {WORDS[0]}-{WORDS[1]}")
    n_par = sum(len(paragraphs(content.get(k, ""))) for k in PARAGRAPH_TOKENS)
    if not PARAGRAPHS[0] <= n_par <= PARAGRAPHS[1]:
        f.append(f"paragraphs: {n_par} body paragraphs; must be {PARAGRAPHS[0]}-{PARAGRAPHS[1]}")
    low = body_text.lower()
    company, title = prof.text(jd.get("company")), prof.text(jd.get("title"))
    if company and company.lower() not in low:
        f.append(f"company: the letter never names {company!r}")
    short_title = re.sub(r"\s*[(\[].*?[)\]]", "", title).split(",")[0].split(" - ")[0].strip()
    if short_title and short_title.lower() not in low:
        f.append(f"role: the letter never names the role {short_title!r}")
    for rx in PLACEHOLDER_RES:
        m = re.search(rx, letter)
        if m:
            f.append(f"placeholder: {m.group(0)!r} left in the letter")
    ptext = profile_text(doc)
    for rx in banned:
        m = re.search(rx, letter, re.I)
        if m and not re.search(rx, ptext, re.I):  # allowed only if the profile itself says it
            f.append(f"leak: mentions {m.group(0)!r}")
    if "!" in body_text:
        f.append("register: exclamation mark")
    for rx in CLICHES:
        m = re.search(rx, low)
        if m:
            f.append(f"register: cliché {m.group(0)!r}")
    # Gate 3, mechanical part: every number must be copied from the profile or the posting.
    source = ptext + "\n" + (prof.text(jd.get("description")) + " " + title).lower()
    for num in sorted(set(re.findall(r"\d+(?:[.,]\d+)?%?", body_text))):
        if num not in source:
            f.append(f"grounding: the number {num!r} is not in the profile or the posting")
    # Gate 9: no new commitments unless the profile says so.
    ans, c = doc.get("answers") or {}, doc["contact"]
    for rx, allowed, what in ((r"salary|compensation|\$\s?\d", prof.text(ans.get("salary_expectation")), "salary"),
                              (r"relocat", prof.text(c.get("willing_to_relocate")).lower() == "yes", "relocation"),
                              (r"start date|available to start|notice period|availability",
                               prof.text(ans.get("notice_period")), "availability")):
        if re.search(rx, low) and not allowed:
            f.append(f"commitment: mentions {what}, which the profile does not settle")
    sig = content.get("SIGNATURE", "")
    name_ok = prof.full_name(doc).lower() in sig.lower() or (
        prof.text(doc["contact"].get("first_name")) + " " + prof.text(doc["contact"].get("last_name"))).lower() in sig.lower()
    if "SIGNATURE" in content and not name_ok:
        f.append(f"signature: must contain {prof.full_name(doc)!r}")
    return f


def render(template, values):
    """Fill tokens; a line that ends up blank because its token was empty is removed."""
    out_lines = []
    for line in template.splitlines():
        had_token = bool(TOKEN_RE.search(line))
        filled = TOKEN_RE.sub(lambda m: values.get(m.group(1), ""), line)
        if had_token and not filled.strip():
            continue
        out_lines.append(filled)
    text = "\n".join(out_lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def facts(doc):
    """The verified material the model may draw on, as plain text."""
    t = prof.text
    lines = [f"Name: {prof.full_name(doc)}", f"Headline: {t(doc.get('headline'))}",
             f"Summary: {t(doc.get('summary'))}", "Experience:"]
    for r in doc["experience"]:
        lines.append(f"- {t(r.get('title'))} at {t(r.get('employer'))} ({t(r.get('start'))} to {t(r.get('end'))})")
        lines += [f"    * {b}" for b in prof.bullets(r)]
    for e in doc["education"]:
        lines.append(f"Education: {t(e.get('degree'))}, {t(e.get('institution'))} {t(e.get('end'))}")
    for g in doc["skills"]:
        lines.append(f"Skills ({t(g.get('group'))}): {', '.join(t(i) for i in g.get('items') or [])}")
    for k in doc["certifications"]:
        if t(k.get("name")):
            lines.append(f"Certification: {t(k.get('name'))}, {t(k.get('issuer'))} {t(k.get('year'))}")
    ans = doc.get("answers") or {}
    if t(ans.get("notice_period")):
        lines.append(f"Notice period (may be stated): {t(ans.get('notice_period'))}")
    return "\n".join(lines)


def _date(d):
    return f"{d:%B} {d.day}, {d.year}"


def prompt_messages(doc, jd, needed, note, samples):
    keys = ", ".join(f'"{k}"' for k in needed)
    system = (
        "You write cover letters for one candidate, in the candidate's own first-person voice. "
        "Use ONLY facts from the candidate profile; copy every number exactly; invent nothing "
        "(no anecdotes, metrics, motivations or skills that are not in the profile). "
        f"Rules: {WORDS[0]}-{WORDS[1]} words from greeting through closing; OPENING, BODY_PARA_1, "
        "BODY_PARA_2, (optional) BODY_PARA_3 and CLOSING are one paragraph each; name the company and "
        "the exact role title; connect at least two verified points to stated requirements; plain, "
        "professional register; no exclamation marks; no clichés ('perfect fit', 'passionate about', "
        "'I am writing to express my interest'); never mention AI, models, automation tools, or how "
        "the letter was written; never state salary, start date or relocation unless the profile does; "
        "no placeholders or brackets. SIGNATURE is a sign-off line plus the candidate's full name. "
        f"Reply with one JSON object with exactly these string keys: {keys}.")
    user = (f"CANDIDATE PROFILE (the only source of facts about the candidate):\n{facts(doc)}\n\n"
            f"JOB: {prof.text(jd.get('title'))} at {prof.text(jd.get('company'))}\n"
            f"POSTING:\n{prof.text(jd.get('description'))[:8000]}\n")
    if note:
        user += f"\nNOTE FROM THE CANDIDATE (an instruction, follow it): {note}\n"
    for s in samples:
        user += f"\nSTYLE SAMPLE (tone and sentence length only; not a source of facts):\n{s[:3000]}\n"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build(doc, jd, template, *, note=None, samples=(), content=None, config_path=None,
          attempts=3, banned=None, today=None):
    """Return (letter_text, content). Raises GateError after the last failing attempt."""
    tokens = list(dict.fromkeys(TOKEN_RE.findall(template)))
    unknown = [t for t in tokens if t not in KIT_TOKENS + MODEL_TOKENS]
    for t in unknown:
        print(f"warning: template token {{{{{t}}}}} is not one the builder knows; it is left out", file=sys.stderr)
    needed = [t for t in tokens if t in MODEL_TOKENS]
    kit = {"FULL_NAME": prof.full_name(doc), "CONTACT_LINE": prof.contact_line(doc),
           "DATE": _date(today or datetime.date.today()),
           "COMPANY": prof.text(jd.get("company")), "ROLE_TITLE": prof.text(jd.get("title"))}
    banned = banned if banned is not None else banned_terms(config_path)
    messages = None if content is not None else prompt_messages(doc, jd, needed, note, samples)
    failures = []
    for _ in range(1 if content is not None else attempts):
        if messages is not None:
            try:
                reply = llm.chat(SLOT, messages, config_path=config_path)
                got = llm.parse_json(reply)
            except llm.LLMError as e:
                if "no JSON" not in str(e):
                    raise
                failures = ["format: the reply was not a JSON object"]
                messages = messages + [{"role": "user", "content": "Reply with the JSON object only."}]
                continue
        else:
            got = content
        got = {k: " ".join(str(v).split()) if k in PARAGRAPH_TOKENS + ("GREETING",) else str(v).strip()
               for k, v in got.items() if k in MODEL_TOKENS and v is not None}
        missing = [k for k in needed if not got.get(k) and k not in OPTIONAL_TOKENS]
        letter = render(template, {**{k: "" for k in unknown}, **kit, **got})
        failures = [f"missing: no content for {k}" for k in missing] + gate(got, letter, doc, jd, banned)
        if not failures:
            return letter, got
        if messages is not None:
            messages = messages + [
                {"role": "assistant", "content": json.dumps(got)},
                {"role": "user", "content": "That letter fails these checks; fix every one and reply "
                                            "with the full JSON again:\n- " + "\n- ".join(failures)}]
    raise GateError(failures)


def to_pdf(letter, pdf_path):
    """The letter as a plain, printable page, rendered like the resume (Chrome)."""
    paras = "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs(letter))
    page = ("<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
            "@page{size:Letter;margin:0.9in 1in}body{font-family:'Helvetica Neue',Helvetica,Arial,"
            "'Liberation Sans',sans-serif;font-size:11pt;line-height:1.45;color:#1a1a1a}"
            "p{margin:0 0 11pt}</style></head><body>" + paras + "</body></html>")
    html_path = Path(pdf_path).with_suffix(".html")
    html_path.write_text(page, encoding="utf-8")
    return build_resume.render_pdf(html_path, pdf_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write a gated cover letter with the cover_letter slot.")
    ap.add_argument("--out", required=True, help="output Markdown path")
    ap.add_argument("--pdf", help="also render the letter to this PDF path")
    ap.add_argument("--jd", help="jd_extract.py JSON (or plain text with --company/--title)")
    ap.add_argument("--company")
    ap.add_argument("--title")
    ap.add_argument("--note", help="the drop's note, verbatim")
    ap.add_argument("--profile", default=str(prof.DEFAULT_PROFILE))
    ap.add_argument("--template", help="default: ~/.hermes/jobdrop/templates/cover_letter.md")
    ap.add_argument("--style-sample", action="append", default=[], help="a writing sample (style only)")
    ap.add_argument("--content", help="gate this JSON content instead of calling the model")
    ap.add_argument("--config", help="model-slot config (default: ~/.hermes/jobdrop/config.yaml)")
    ap.add_argument("--attempts", type=int, default=3)
    args = ap.parse_args(argv)
    try:
        doc = prof.load_profile(args.profile)
        jd = build_resume.load_jd(args.jd) if args.jd else {}
        jd["company"] = args.company or jd.get("company") or ""
        jd["title"] = args.title or jd.get("title") or ""
        if not jd["company"] or not jd["title"]:
            raise ValueError("need the company and the role title (from --jd JSON, or --company/--title)")
        tpl = Path(args.template) if args.template else build_resume.user_file("cover_letter.md")
        content = json.loads(Path(args.content).read_text(encoding="utf-8")) if args.content else None
        samples = [Path(s).read_text(encoding="utf-8", errors="replace") for s in args.style_sample]
        letter, _ = build(doc, jd, tpl.read_text(encoding="utf-8"), note=args.note, samples=samples,
                          content=content, config_path=args.config, attempts=args.attempts)
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(letter, encoding="utf-8")
        msg = f"wrote {out} ({len(words(letter))} words, all gates passed)"
        if args.pdf:
            to_pdf(letter, Path(args.pdf).expanduser())
            msg += f" and {args.pdf}"
        print(msg)
        return 0
    except GateError as e:
        print("error: the letter failed its gates; nothing written:\n  - " + "\n  - ".join(e.failures),
              file=sys.stderr)
        return 2
    except (llm.LLMError, build_resume.BuildError, prof.ProfileError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
