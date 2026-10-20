#!/usr/bin/env python3
"""Build a tailored resume: verified profile (+ job description) → filled HTML → PDF.

    python3 scripts/build_resume.py --out DIR/resume.pdf [--profile P] [--template T]
                                    [--jd jd.json | --selection sel.json] [--config C]
                                    [--warn-unknown-tokens] [--html-only]

The profile supplies every word. The job description only SELECTS and ORDERS verified
bullets (via the `resume` slot, or a selection file), never rewrites one. A core role that
cannot appear fails the build loudly, naming the role.

Selection file / `resume` slot reply shape (bullet ids are listed by the builder):
    {"roles": {"r0": ["r0b2", "r0b0"], "r1": ["r1b1"]}, "summary": "optional trimmed summary"}
A role id absent from "roles" is dropped (allowed for non-core roles only).

PDF rendering: the user's Chrome, headless, with a throwaway profile and a 60s timeout;
WeasyPrint if Chrome is absent and WeasyPrint is installed.
"""
import argparse
import html
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import profile as prof  # noqa: E402

TEXT_TOKENS = ("FULL_NAME", "FIRST_NAME", "LAST_NAME", "HEADLINE", "CONTACT_LINE", "SUMMARY",
               "EMAIL", "PHONE", "CITY", "STATE", "LOCATION", "LINKEDIN", "GITHUB", "PORTFOLIO")
HTML_TOKENS = ("EXPERIENCE", "SKILLS", "EDUCATION", "CERTIFICATIONS")
KNOWN_TOKENS = set(TEXT_TOKENS + HTML_TOKENS)
TOKEN_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)  # template docs live in comments; never rendered
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class BuildError(Exception):
    """The resume cannot be built honestly. The message says exactly why."""


def user_file(name):
    """~/.hermes/jobdrop/templates/<name>, else the repo's shipped copy (running from a clone)."""
    for p in (Path("~/.hermes/jobdrop/templates").expanduser() / name, HERE.parent / "templates" / name):
        if p.is_file():
            return p
    raise BuildError(f"template {name} not found in ~/.hermes/jobdrop/templates/; run install.sh")


# ---- selection (the only thing a job description may influence) ----------------------------

def bullet_catalog(doc):
    """{role_id: [(bullet_id, text), ...]} — the verified bullets the resume slot chooses from."""
    return {f"r{i}": [(f"r{i}b{j}", b) for j, b in enumerate(prof.bullets(r))]
            for i, r in enumerate(doc["experience"])}


def check_core_roles(doc):
    """Every core role must be renderable. Raises BuildError naming each one that is not."""
    roles = doc["experience"]
    if not roles:
        raise BuildError("profile has no experience roles; a resume needs at least one")
    bad = []
    for r in roles:
        if not r.get("core", False):
            continue
        name = f"{prof.text(r.get('title')) or '?'} at {prof.text(r.get('employer')) or '?'}"
        missing = [k for k in ("employer", "title") if not prof.text(r.get(k))]
        if not prof.bullets(r):
            missing.append("bullets")
        if missing:
            bad.append(f"{name} (missing {', '.join(missing)})")
    if bad:
        raise BuildError("core role(s) cannot appear on the resume: " + "; ".join(bad)
                         + ". Fix the profile — core roles are never silently dropped.")


def _sentences(s):
    return [x for x in re.split(r"(?<=[.!?])\s+", " ".join(s.split())) if x]


def apply_selection(doc, selection, warn):
    """Return (roles_to_render, summary). Enforces select-never-rewrite and core roles."""
    catalog = bullet_catalog(doc)
    roles = doc["experience"]
    summary = prof.text(doc.get("summary"))
    if not selection:
        return [(r, prof.bullets(r)) for r in roles], summary

    chosen = selection.get("roles") or {}
    if not isinstance(chosen, dict):
        raise BuildError("selection.roles must map role ids to bullet-id lists")
    out = []
    dropped_core = []
    for i, r in enumerate(roles):
        rid = f"r{i}"
        if rid not in chosen:
            if r.get("core", False):
                dropped_core.append(f"{prof.text(r.get('title'))} at {prof.text(r.get('employer'))}")
            continue
        texts = dict(catalog[rid])
        picked = []
        for bid in chosen[rid] or []:
            if bid not in texts:
                warn(f"selection names unknown bullet id {bid!r} for {rid}; ignored")
            elif texts[bid] not in picked:
                picked.append(texts[bid])
        for _, t in catalog[rid]:  # each kept role keeps at least two bullets (or all it has)
            if len(picked) >= min(2, len(catalog[rid])):
                break
            if t not in picked:
                picked.append(t)
        out.append((r, picked))
    if dropped_core:
        raise BuildError("tailoring dropped core role(s): " + "; ".join(dropped_core)
                         + ". Core roles must appear on every resume.")
    unknown = sorted(set(chosen) - set(catalog))
    if unknown:
        warn(f"selection names unknown role id(s) {', '.join(unknown)}; ignored")

    picked_summary = prof.text(selection.get("summary"))
    if picked_summary:
        verified = set(_sentences(summary))
        if all(s in verified for s in _sentences(picked_summary)):
            summary = picked_summary
        else:
            warn("selected summary is not made of verified summary sentences; using the profile summary")
    return out, summary


def select_with_model(doc, jd, config_path, warn):
    """Ask the `resume` slot which verified bullets fit this job. Returns a selection dict."""
    import llm
    catalog = bullet_catalog(doc)
    lines = []
    for i, r in enumerate(doc["experience"]):
        rid = f"r{i}"
        lines.append(f"{rid}: {prof.text(r.get('title'))} at {prof.text(r.get('employer'))}"
                     f"{' (core: must keep)' if r.get('core') else ''}")
        lines += [f"  {bid}: {t}" for bid, t in catalog[rid]]
    prompt = (
        "Choose which of the candidate's VERIFIED resume bullets best fit this job, most relevant "
        "first. You may only select bullet ids from the list; never write new text. Keep every role "
        "marked core. Keep 2-5 bullets per kept role. For the summary, you may return a subset of the "
        "summary's sentences copied exactly, or omit it.\n\n"
        f"JOB: {jd.get('title', '')} at {jd.get('company', '')}\n{(jd.get('description') or '')[:6000]}\n\n"
        f"SUMMARY: {prof.text(doc.get('summary'))}\n\nBULLETS:\n" + "\n".join(lines) +
        '\n\nReply with JSON only: {"roles": {"r0": ["r0b1", ...], ...}, "summary": "..."}')
    try:
        reply = llm.chat("resume", [{"role": "user", "content": prompt}], config_path=config_path)
        return llm.parse_json(reply)
    except llm.LLMError as e:
        warn(f"resume slot unavailable ({e}); using every verified bullet in profile order")
        return None


# ---- rendering -----------------------------------------------------------------------------

def fmt_date(v):
    v = prof.text(v)
    if v.lower() in ("present", "current", "now"):
        return "Present"
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", v)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
    return v


def date_range(item):
    a, b = fmt_date(item.get("start")), fmt_date(item.get("end"))
    return f"{a} – {b}" if a and b else a or b


def block(title, dates, sub_strong, sub_rest, items):
    e = html.escape
    sub = " · ".join(x for x in (f'<span class="role-employer">{e(sub_strong)}</span>' if sub_strong else "",
                                 e(sub_rest)) if x)
    lis = "".join(f"<li>{e(t)}</li>" for t in items)
    return (f'<div class="role">\n  <div class="role-head"><span class="role-title">{e(title)}</span>'
            f'<span class="role-dates">{e(dates)}</span></div>\n'
            + (f'  <div class="role-sub">{sub}</div>\n' if sub else "")
            + (f"  <ul>{lis}</ul>\n" if lis else "") + "</div>")


def token_values(doc, roles, summary):
    t = prof.text
    c = doc["contact"]
    links = doc.get("links") or {}
    exp = "\n".join(block(t(r.get("title")), date_range(r), t(r.get("employer")), t(r.get("location")), bl)
                    for r, bl in roles)
    edu = "\n".join(block(t(e.get("degree")) or t(e.get("institution")), fmt_date(e.get("end")),
                          t(e.get("institution")) if t(e.get("degree")) else "", t(e.get("location")),
                          [t(d) for d in e.get("details") or [] if t(d)])
                    for e in doc["education"] if t(e.get("institution")) or t(e.get("degree")))
    skills = "\n".join(
        f'<p class="skill-line">' + (f"<strong>{html.escape(t(g.get('group')))}:</strong> " if t(g.get("group")) else "")
        + html.escape(", ".join(t(i) for i in g.get("items") or [] if t(i))) + "</p>"
        for g in doc["skills"] if any(t(i) for i in g.get("items") or []))
    certs = "\n".join(
        f'<p class="cert">{html.escape(" — ".join(x for x in (t(k.get("name")), ", ".join(y for y in (t(k.get("issuer")), t(k.get("year"))) if y)) if x))}</p>'
        for k in doc["certifications"] if t(k.get("name")))
    recent = roles[0][0] if roles else {}
    text_vals = {
        "FULL_NAME": prof.full_name(doc), "FIRST_NAME": prof.first_name(doc), "LAST_NAME": t(c.get("last_name")),
        "HEADLINE": t(doc.get("headline")) or t(recent.get("title")), "CONTACT_LINE": prof.contact_line(doc),
        "SUMMARY": summary, "EMAIL": t(c.get("email")), "PHONE": t(c.get("phone")), "CITY": t(c.get("city")),
        "STATE": t(c.get("state")), "LOCATION": prof.location(doc), "LINKEDIN": t(links.get("linkedin")),
        "GITHUB": t(links.get("github")), "PORTFOLIO": t(links.get("portfolio")),
    }
    vals = {k: html.escape(v) for k, v in text_vals.items()}
    vals.update(EXPERIENCE=exp, SKILLS=skills, EDUCATION=edu, CERTIFICATIONS=certs)
    return vals


def unknown_tokens(template):
    """[(token, line_no)] for tokens the builder does not know."""
    blanked = COMMENT_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), template)  # keep line numbers
    return [(m.group(1), blanked.count("\n", 0, m.start()) + 1)
            for m in TOKEN_RE.finditer(blanked) if m.group(1) not in KNOWN_TOKENS]


def fill(template, vals):
    """Substitute known tokens; unknown ones stay visible. Drop empty <section data-optional>."""
    out = TOKEN_RE.sub(lambda m: vals.get(m.group(1), m.group(0)), COMMENT_RE.sub("", template))

    def drop_empty(m):
        inner = re.sub(r"<h[1-6][^>]*>.*?</h[1-6]>", "", m.group(0), flags=re.S | re.I)
        inner = re.sub(r"<section[^>]*>|</section>", "", inner, flags=re.I)
        return m.group(0) if re.sub(r"<[^>]+>|\s", "", inner) else ""

    return re.sub(r"<section\b[^>]*\bdata-optional\b[^>]*>.*?</section>", drop_empty, out, flags=re.S | re.I)


def build_html(doc, template, selection=None, warn=print):
    check_core_roles(doc)
    roles, summary = apply_selection(doc, selection, warn)
    return fill(template, token_values(doc, roles, summary))


# ---- PDF -----------------------------------------------------------------------------------

def find_chrome():
    env = os.environ.get("CHROME_BIN")
    if env and shutil.which(env):
        return shutil.which(env)
    for name in CHROME_NAMES:
        if shutil.which(name):
            return shutil.which(name)
    return MAC_CHROME if Path(MAC_CHROME).exists() else None


def is_pdf(path):
    p = Path(path)
    if not p.is_file() or p.stat().st_size < 200:
        return False
    data = p.read_bytes()
    return data.startswith(b"%PDF-") and b"%%EOF" in data[-1024:]


def page_count(path):
    return len(re.findall(rb"/Type\s*/Page(?!s)", Path(path).read_bytes()))


def render_pdf(html_path, pdf_path, timeout=60):
    """HTML file → PDF with headless Chrome (throwaway profile, hard timeout), else WeasyPrint."""
    html_path, pdf_path = Path(html_path).resolve(), Path(pdf_path).resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    if pdf_path.exists():
        pdf_path.unlink()
    chrome = find_chrome()
    if chrome:
        with tempfile.TemporaryDirectory(prefix="jobdrop-chrome-") as ud:
            cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
                   "--no-default-browser-check", "--no-pdf-header-footer", f"--user-data-dir={ud}",
                   "--virtual-time-budget=5000", f"--print-to-pdf={pdf_path}", html_path.as_uri()]
            # Own process group, so a hung Chrome and all its helpers die together. Headless
            # Chrome often writes the PDF and then never exits: stop it once the file is
            # complete and stable, or at the timeout.
            log = Path(ud) / "stderr.log"
            with open(log, "wb") as errf:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=errf, start_new_session=True)
                deadline, last = time.monotonic() + timeout, -1
                while proc.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.25)
                    size = pdf_path.stat().st_size if pdf_path.exists() else -1
                    if size == last and is_pdf(pdf_path):
                        break
                    last = size
                if proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
            if is_pdf(pdf_path):
                return "chrome"
            tail = log.read_text("utf-8", "replace").strip().splitlines()[-3:]
            raise BuildError(f"Chrome did not produce a PDF ({chrome}): " + " | ".join(tail))
    try:
        import weasyprint
    except ImportError:
        raise BuildError("no PDF renderer: install Google Chrome/Chromium (or set $CHROME_BIN), "
                         "or `pip install weasyprint` as a fallback")
    weasyprint.HTML(filename=str(html_path)).write_pdf(str(pdf_path))
    if not is_pdf(pdf_path):
        raise BuildError("WeasyPrint did not produce a valid PDF")
    return "weasyprint"


def load_jd(path):
    """A jd_extract.py JSON file, or plain text (treated as the description)."""
    raw = Path(path).read_text(encoding="utf-8")
    try:
        jd = json.loads(raw)
        if isinstance(jd, dict):
            return jd
    except ValueError:
        pass
    return {"description": raw}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a tailored resume PDF from the verified profile.")
    ap.add_argument("--out", required=True, help="output PDF path (the filled .html is written beside it)")
    ap.add_argument("--profile", default=str(prof.DEFAULT_PROFILE))
    ap.add_argument("--template", help="resume HTML template (default: ~/.hermes/jobdrop/templates/resume.html)")
    ap.add_argument("--jd", help="job description: jd_extract.py JSON or plain text; uses the `resume` slot")
    ap.add_argument("--selection", help="bullet selection JSON (skips the model)")
    ap.add_argument("--config", help="model-slot config (default: ~/.hermes/jobdrop/config.yaml)")
    ap.add_argument("--warn-unknown-tokens", action="store_true",
                    help="list each unknown {{TOKEN}} with its line number (the build still runs)")
    ap.add_argument("--html-only", action="store_true", help="write the filled HTML, skip the PDF")
    args = ap.parse_args(argv)
    warn = lambda m: print(f"warning: {m}", file=sys.stderr)  # noqa: E731
    try:
        doc = prof.load_profile(args.profile)
        tpl_path = Path(args.template) if args.template else user_file("resume.html")
        template = tpl_path.read_text(encoding="utf-8")
        unknown = unknown_tokens(template)
        if unknown:
            names = sorted({t for t, _ in unknown})
            warn(f"template {tpl_path.name} has {len(unknown)} unknown token(s): {', '.join(names)} "
                 f"(left visible; known: {', '.join(sorted(KNOWN_TOKENS))})")
            if args.warn_unknown_tokens:
                for tok, line in unknown:
                    warn(f"  {tpl_path.name}:{line}: {{{{{tok}}}}}")
        check_core_roles(doc)
        selection = None
        if args.selection:
            selection = json.loads(Path(args.selection).read_text(encoding="utf-8"))
        elif args.jd:
            selection = select_with_model(doc, load_jd(args.jd), args.config, warn)
        filled = build_html(doc, template, selection, warn)
        out = Path(args.out).expanduser()
        html_out = out.with_suffix(".html")
        html_out.parent.mkdir(parents=True, exist_ok=True)
        html_out.write_text(filled, encoding="utf-8")
        if args.html_only:
            print(f"wrote {html_out}")
            return 0
        engine = render_pdf(html_out, out)
        print(f"wrote {out} ({page_count(out)} page(s), {engine}) and {html_out.name}")
        return 0
    except (BuildError, prof.ProfileError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
