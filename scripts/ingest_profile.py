#!/usr/bin/env python3
"""Draft ~/.hermes/jobdrop/profile.yaml from a folder of your own resumes and documents.

    python3 scripts/ingest_profile.py ~/my-career [--out PATH | --out -] [--force]

Walks the folder (or reads one file): PDF, DOCX, ODT, HTML, MD, TXT, plus any profile-shaped
YAML/JSON, which takes precedence over everything extracted. Segments resumes into contact
block, summary, roles, education, skills, certifications and links, merges all files, and
writes a DRAFT for you to review once.

It never invents. A field not found in your files stays empty and is listed under "needs
your input". Contact details come only from resume-like documents (a cover letter's header
may hold someone else's address). Same folder in → same draft out.

PDF text needs `pypdf` (or `pdfplumber`, or poppler's `pdftotext`); DOCX/ODT/HTML/MD/TXT are
read with the standard library (python-docx is used if installed). A missing reader skips
that file with a message — it never crashes the run.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import profile as prof  # noqa: E402

TEXT_TYPES = {".pdf", ".docx", ".odt", ".html", ".htm", ".md", ".markdown", ".txt", ".text"}
STRUCTURED_TYPES = {".yaml", ".yml", ".json"}
SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".venv"}
PROFILE_KEYS = {"contact", "experience", "education", "skills", "summary", "certifications", "links"}

SECTIONS = {
    "summary": "summary|professional summary|profile|professional profile|about|about me|objective|"
               "career objective|career summary|overview|executive summary|personal statement",
    "experience": "experience|work experience|professional experience|employment|employment history|"
                  "work history|career history|relevant experience|professional background|career",
    "education": "education|academic background|education and training|academics|education & training",
    "skills": "skills|technical skills|core skills|key skills|competencies|core competencies|technologies|"
              "tools|skills and tools|skills & tools|tools and technologies|tools & technologies|"
              "areas of expertise|expertise|skills & expertise|skills and expertise",
    "certifications": "certifications|certification|certificates|licenses|licences|credentials|"
                      "licenses and certifications|licenses & certifications|certifications and licenses|"
                      "certifications & licenses",
    "links": "links|online|profiles|online presence",
    "other": "projects|selected projects|volunteer|volunteering|volunteer experience|publications|awards|"
             "honors|honours|honors and awards|honors & awards|interests|languages|references|activities|"
             "leadership|affiliations|memberships|patents|speaking|talks|additional information",
}
HEADINGS = {name: kind for kind, names in SECTIONS.items() for name in names.split("|")}

BULLET_RE = re.compile(r"^\s*(?:[•·▪◦‣●○■□➢►▶✓✔❖]\s*|[-–—*+]\s+|\d{1,2}[.)]\s+)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<![\w/])\+?\(?\d[\d\s().-]{5,}\d(?![\w/])")
URL_RE = re.compile(r"(?:https?://)?(?:www\.)?(?:linkedin\.com/in/[\w%-]+|github\.com/[\w.-]+)/?"
                    r"|https?://[^\s,;|<>()\[\]\"']+", re.I)
BARE_DOMAIN_RE = re.compile(r"(?<![@\w.])(?:[a-z0-9-]+\.)+(?:com|org|net|io|dev|me|co|ai|app|site|"
                            r"xyz|info|page|blog|tech)(?:/[^\s,;|]*)?(?![\w@])", re.I)
MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
         r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?")
DATE = rf"(?:{MONTH}\s*,?\s*\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}}-\d{{2}}|\d{{4}})"
RANGE_RE = re.compile(rf"({DATE})\s*(?:-|–|—|to|until|through)\s*({DATE}|present|current|now|today)", re.I)
YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
LOCATION_RE = re.compile(
    r"^(?:(?:location|based in|address)\s*[:\-]\s*)?([A-Z][A-Za-z.'’-]+(?: [A-Z][A-Za-z.'’-]+){0,3}),\s*"
    r"([A-Z]{2}|[A-Z][a-z]+(?: [A-Z][a-z]+){0,2})(?:\s+(\d{5}(?:-\d{4})?|[A-Z]\d[A-Z] ?\d[A-Z]\d))?"
    r"(?:,\s*([A-Z][A-Za-z ]+))?$")
REMOTE_RE = re.compile(r"^\(?(remote|hybrid|on-?site)(?:\s*[-–(].*)?\)?$", re.I)
COUNTRIES = {"united states", "usa", "us", "u.s.", "united states of america", "canada", "united kingdom",
             "uk", "england", "scotland", "ireland", "germany", "france", "spain", "italy", "netherlands",
             "belgium", "sweden", "norway", "denmark", "finland", "switzerland", "austria", "poland",
             "portugal", "india", "australia", "new zealand", "singapore", "japan", "mexico", "brazil",
             "argentina", "south africa", "israel"}
TITLE_WORDS = re.compile(
    r"\b(engineer|engineering|manager|director|analyst|developer|designer|lead|head|consultant|associate|"
    r"specialist|scientist|architect|officer|coordinator|intern|president|vp|vice president|founder|"
    r"co-founder|administrator|assistant|representative|executive|accountant|writer|editor|teacher|"
    r"nurse|technician|strategist|advisor|adviser|partner|principal|researcher|programmer|owner|"
    r"supervisor|chief|cto|ceo|cfo|coo|staff|senior|junior|fellow|instructor|professor|counsel|attorney|"
    r"recruiter|marketer|producer|planner|operator|clerk|agent|tutor|trainer|sre|devops)\b", re.I)
EMPLOYER_WORDS = re.compile(
    r"\b(inc|llc|ltd|corp|corporation|co|company|group|gmbh|plc|llp|labs?|technologies|technology|"
    r"systems|solutions|software|analytics|consulting|logistics|health|bank|agency|partners|studio|"
    r"university|college|institute|foundation|hospital|capital|holdings|ventures|media|industries)\b\.?", re.I)
INSTITUTION_WORDS = re.compile(r"\b(university|college|institute|school|academy|polytechnic|conservatory)\b", re.I)
DEGREE_WORDS = re.compile(
    r"\b(b\.?\s?s\.?c?|b\.?\s?a\.?|b\.?\s?eng|m\.?\s?s\.?c?|m\.?\s?a\.?|m\.?\s?eng|mba|ph\.?\s?d|j\.?d|m\.?d|"
    r"bachelor'?s?|master'?s?|associate'?s?|doctor(ate)?|diploma|certificate|a\.?a\.?s?|bsc|msc|ba|bs|ma|ms)\b",
    re.I)
SPLIT_RE = re.compile(r"\s+[—–|·•@]\s+|\s+-\s+|\s+at\s+|\t|\s{3,}")


# ---- reading files -------------------------------------------------------------------------

class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "section",
             "article", "header", "footer", "table", "dd", "dt", "blockquote", "pre", "address"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.hrefs, self._skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self._skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "li":
            self.out.append("• ")
        href = dict(attrs).get("href") if tag == "a" else None
        if href and href.startswith(("http://", "https://")):
            self.hrefs.append(href)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template") and self._skip:
            self._skip -= 1
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def read_html(raw):
    p = _Text()
    p.feed(raw)
    text = "".join(p.out)
    # Links that only live in an href are grounded too: append the ones the text lacks.
    extra = [h for h in dict.fromkeys(p.hrefs) if h not in text and URL_RE.fullmatch(h.rstrip("/"))]
    return text + ("\n" + "\n".join(extra) if extra else "")


def read_pdf(path):
    try:
        import pypdf
        return "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(str(path)).pages)
    except ImportError:
        pass
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except ImportError:
        pass
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, timeout=60)
        if r.returncode == 0:
            return r.stdout.decode("utf-8", "replace")
    raise MissingReader("no PDF reader: python3 -m pip install --user pypdf")


def read_docx(path):
    try:
        import docx
        d = docx.Document(str(path))
        return "\n".join(("• " if (p.style.name or "").lower().startswith("list") else "") + p.text
                         for p in d.paragraphs)
    except ImportError:
        pass
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    paras = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        t = "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>|<w:tab/>", p))
        paras.append(("• " if "<w:numPr>" in p else "") + _unxml(t))
    return "\n".join(paras)


def read_odt(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("content.xml").decode("utf-8", "replace")
    paras = re.findall(r"<text:(?:p|h)[^>]*>(.*?)</text:(?:p|h)>", xml, re.S)
    return "\n".join(_unxml(re.sub(r"<[^>]+>", "", p)) for p in paras)


def _unxml(s):
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")


def read_markdown(raw):
    lines = []
    for line in raw.splitlines():
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)            # headings → plain lines
        line = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 \2", line)  # [text](url) → text url
        line = re.sub(r"(\*\*|__|`)", "", line)
        lines.append(line)
    return "\n".join(lines)


class MissingReader(Exception):
    pass


def read_text(path):
    ext = path.suffix.lower()
    if ext == ".pdf":
        return read_pdf(path)
    if ext == ".docx":
        return read_docx(path)
    if ext == ".odt":
        return read_odt(path)
    raw = path.read_text(encoding="utf-8", errors="replace")
    if ext in (".html", ".htm"):
        return read_html(raw)
    if ext in (".md", ".markdown"):
        return read_markdown(raw)
    return raw


def read_structured(path):
    """A profile-shaped mapping from YAML/JSON, or None if the file is something else."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(raw)
        else:
            import yaml
            data = yaml.safe_load(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) and PROFILE_KEYS & set(data) else None


def collect(root):
    root = Path(root).expanduser()
    if root.is_file():
        return [root]
    files = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).parts
        if any(part.startswith(".") or part in SKIP_DIRS for part in rel[:-1]) or p.name.startswith((".", "~$")):
            continue
        if p.is_file() and p.suffix.lower() in TEXT_TYPES | STRUCTURED_TYPES:
            files.append(p)
    return files


# ---- segmenting one document ---------------------------------------------------------------

def clean_line(line):
    line = line.replace(" ", " ").replace("​", "").strip()
    toks = line.split(" ")
    # "S U M M A RY" — letter-spaced headings from PDFs
    if len(toks) >= 4 and all(len(t) <= 2 for t in toks) and sum(len(t) == 1 for t in toks) >= len(toks) - 1:
        line = "".join(toks)
    return " ".join(line.split())


def heading_kind(line):
    key = re.sub(r"[:\s]+$", "", line).strip().lower()
    key = " ".join(key.split())
    if len(key.split()) > 5:
        return None
    return HEADINGS.get(key) or HEADINGS.get(key.replace("&", "and"))


def lines_of(text):
    """[(text, is_bullet)] with blank lines dropped."""
    out = []
    for raw in text.splitlines():
        is_bullet = bool(BULLET_RE.match(raw))
        line = clean_line(BULLET_RE.sub("", raw, count=1) if is_bullet else raw)
        if line:
            out.append((line, is_bullet))
    return out


def sections(lines):
    """{'header': [...], 'summary': [...], ...} — consecutive same-kind sections are concatenated."""
    out = {"header": []}
    cur = "header"
    for line, b in lines:
        kind = None if b else heading_kind(line)
        if kind:
            cur = kind
            out.setdefault(cur, [])
            continue
        out.setdefault(cur, []).append((line, b))
    return out


def norm_date(s):
    s = s.strip().lower().rstrip(".")
    if s in ("present", "current", "now", "today"):
        return "present"
    m = re.fullmatch(r"(\d{4})-(\d{2})", s)
    if m:
        return s
    m = re.fullmatch(r"(\d{1,2})/(\d{4})", s)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = re.fullmatch(rf"({MONTH})\s*,?\s*(\d{{4}})", s)
    if m:
        months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
        return f"{m.group(2)}-{months.index(m.group(1)[:3]) + 1:02d}"
    return s if re.fullmatch(r"\d{4}", s) else ""


def parse_location(part):
    """(city, state, postal, country) for 'City, ST 12345' / 'City, Country' parts, else None."""
    m = LOCATION_RE.match(part.strip())
    if not m:
        return None
    city, region, postal, country = m.group(1), m.group(2), m.group(3) or "", m.group(4) or ""
    # A role heading like "Senior Software Engineer, Northwind Systems" is TWO PROPER-NAMED
    # pieces, not a "City, ST" pair. LOCATION_RE happily matched it (city="Senior Software
    # Engineer", region="Northwind Systems") because "Northwind Systems" is two words, so
    # split_head consumed the WHOLE heading as a location and the role lost its title and
    # employer. A city is not a job title and not a company name: reject both.
    if TITLE_WORDS.search(city) or EMPLOYER_WORDS.search(city):
        return None
    if TITLE_WORDS.search(region) or EMPLOYER_WORDS.search(region):
        return None
    if region.lower() in COUNTRIES and not country:
        return city, "", postal, region
    if country and country.lower() not in COUNTRIES:
        return None
    if not re.fullmatch(r"[A-Z]{2}", region) and len(region.split()) > 2:
        return None
    return city, region, postal, country


def find_phone(text):
    for m in PHONE_RE.finditer(text):
        cand = m.group(0).strip()
        digits = re.sub(r"\D", "", cand)
        if not 7 <= len(digits) <= 15:
            continue
        if RANGE_RE.search(cand) or re.fullmatch(r"[\d\s/-]*", cand) and YEAR_RE.findall(cand) and \
                len(digits) == 4 * len(YEAR_RE.findall(cand)):
            continue  # "2018 - 2021" is a date range, not a phone number
        if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", cand):
            continue
        return cand
    return ""


def links_in(text, header_lines):
    found = []
    for m in URL_RE.finditer(text):
        found.append(m.group(0))
    for line in header_lines:  # bare personal domains only count in the contact block
        for m in BARE_DOMAIN_RE.finditer(EMAIL_RE.sub(" ", line)):
            found.append(m.group(0))
    out = {"linkedin": "", "github": "", "portfolio": "", "other": []}
    for u in dict.fromkeys(x.rstrip("/.,") for x in found):
        full = u if u.lower().startswith("http") else "https://" + u
        low = full.lower()
        if "linkedin.com/in/" in low:
            out["linkedin"] = out["linkedin"] or full
        elif re.search(r"github\.com/[\w.-]+$", low):
            out["github"] = out["github"] or full
        elif not out["portfolio"] and not re.search(r"linkedin\.com|github\.com", low):
            out["portfolio"] = full
        elif full not in out["other"] and full not in (out["portfolio"],):
            out["other"].append(full)
    return out


def parse_header(header, text):
    """Contact block: name, headline, email, phone, location, from the resume's top lines."""
    c, notes = {}, []
    lines = [l for l, _ in header]
    emails = list(dict.fromkeys(EMAIL_RE.findall(text)))
    if emails:
        c["email"] = emails[0]
    head_text = "\n".join(lines)
    c["phone"] = find_phone(head_text) or find_phone(text)
    name_at = None
    for i, line in enumerate(lines[:6]):
        cand = re.sub(r",\s*(ph\.?d|mba|cpa|pe|pmp|md|jd|msc?|bsc?)\.?$", "", line, flags=re.I).strip()
        toks = cand.split()
        if 2 <= len(toks) <= 4 and not re.search(r"[@\d/:|•·]", cand) and not heading_kind(cand) and \
                all(re.fullmatch(r"[A-Z][A-Za-z'’.-]*", t) for t in toks) and not TITLE_WORDS.search(cand):
            if cand.isupper():
                toks = [t.capitalize() for t in toks]
            c["first_name"], c["last_name"] = toks[0], toks[-1]
            if len(toks) > 2:
                notes.append(f"name '{' '.join(toks)}' split as first={toks[0]} last={toks[-1]}; check it")
            name_at = i
            break
    for line in lines:
        for part in re.split(r"\s+[·|•]\s+|\s{2,}|\t", line):
            loc = parse_location(re.sub(r"^(location|address)\s*[:\-]\s*", "", part, flags=re.I))
            if loc and "city" not in c:
                c["city"], c["state"], c["postal_code"], c["country"] = loc
    if name_at is not None and name_at + 1 < len(lines):
        nxt = lines[name_at + 1]
        if not re.search(r"@|\d|https?:|www\.|linkedin|github", nxt, re.I) and not parse_location(nxt) \
                and len(nxt.split()) <= 10:
            c["headline"] = nxt
    return {k: v for k, v in c.items() if v}, notes


def _protect(s):
    # keep "Acme, Inc." together when splitting on commas
    return re.sub(r",\s*(?=(inc|llc|ltd|corp|co|gmbh|plc|llp|s\.a)\b)", "\x00", s, flags=re.I)


def split_head(head_lines):
    """Pull dates and location out of a role's heading lines; return (start, end, location, parts)."""
    start = end = location = ""
    parts = []
    for line in head_lines:
        m = RANGE_RE.search(line)
        if m and not start:
            start, end = norm_date(m.group(1)), norm_date(m.group(2))
            line = (line[:m.start()] + " | " + line[m.end():]).strip()
        line = re.sub(r"\((remote|hybrid|on-?site)\)", r"| \1", line, flags=re.I)
        for p in SPLIT_RE.split(line):
            p = p.strip(" ,|()-–—")
            if not p:
                continue
            if not location and (REMOTE_RE.match(p) or parse_location(p)):
                location = p
                continue
            # "Data Engineer, Acme Corp" or "Acme Corp, Lakeview, CO"
            sub = [x.replace("\x00", ", ").strip() for x in _protect(p).split(",")]
            if len(sub) >= 3 and not location and parse_location(", ".join(sub[-2:])):
                location = ", ".join(sub[-2:])
                sub = sub[:-2]
            parts += [x for x in sub if x]
    return start, end, location, parts


def assign_title_employer(parts):
    """(title, employer, ambiguous) from the non-date, non-location pieces of a role heading."""
    if not parts:
        return "", "", True
    if len(parts) == 1:
        p = parts[0]
        return (p, "", True) if TITLE_WORDS.search(p) else ("", p, True)
    title = next((p for p in parts if TITLE_WORDS.search(p) and not EMPLOYER_WORDS.search(p)), "") or \
        next((p for p in parts if TITLE_WORDS.search(p)), "")
    employer = next((p for p in parts if p != title and EMPLOYER_WORDS.search(p)), "")
    rest = [p for p in parts if p not in (title, employer)]
    ambiguous = not (title and employer)
    if not title and rest:
        title = rest.pop(0)
    if not employer and rest:
        employer = rest.pop(0)
    return title, employer, ambiguous


def _is_continuation(line, prev):
    if re.match(r"[a-z0-9(%&,;]", line):
        return True
    if RANGE_RE.search(line):
        return False
    short_headish = len(line.split()) <= 7 and not line.endswith(".")
    return not re.search(r"[.!?;:)]$", prev) and not short_headish


def _content_like(line):
    """A sentence of achievement text rather than a role heading (bullet glyphs are often lost)."""
    if RANGE_RE.search(line):
        return False
    n = len(line.split())
    return (n >= 5 and line.endswith(".")) or (n >= 8 and not re.search(r"\s[·|•]\s", line))


def parse_roles(lines):
    entries, cur = [], None
    for line, is_bullet in lines:
        if cur and cur["bullets"] and not is_bullet and _is_continuation(line, cur["bullets"][-1]):
            cur["bullets"][-1] += " " + line  # a bullet wrapped onto the next line
            continue
        head_done = cur and (len(cur["head"]) >= 2 or any(RANGE_RE.search(h) for h in cur["head"]))
        if is_bullet or (head_done and _content_like(line)):
            cur = cur or {"head": [], "bullets": []}
            cur["bullets"].append(line)
            continue
        if cur and (cur["bullets"] or (RANGE_RE.search(line) and any(RANGE_RE.search(h) for h in cur["head"]))):
            entries.append(cur)  # a heading after bullets, or a second dated heading: a new role
            cur = None
        cur = cur or {"head": [], "bullets": []}
        cur["head"].append(line)
    if cur:
        entries.append(cur)
    roles, notes = [], []
    for e in entries:
        if not e["head"]:
            continue
        start, end, location, parts = split_head(e["head"])
        title, employer, ambiguous = assign_title_employer(parts)
        role = {"employer": employer, "title": title, "location": location, "start": start, "end": end,
                "core": True, "bullets": e["bullets"]}
        roles.append(role)
        if ambiguous:
            notes.append(f"role '{' / '.join(e['head'])}': read as title={title!r}, employer={employer!r}; check it")
    return roles, notes


def parse_education(lines):
    out, cur = [], None

    def push():
        if cur and (cur["institution"] or cur["degree"]):
            out.append(cur)

    for line, is_bullet in lines:
        if is_bullet and cur:
            cur["details"].append(line)
            continue
        m = RANGE_RE.search(line)
        year = norm_date(m.group(2)) if m else (YEAR_RE.findall(line) or [""])[-1]
        rest = RANGE_RE.sub(" | ", line) if m else YEAR_RE.sub(" | ", line) if year else line
        for part in SPLIT_RE.split(rest):
            for p in [x.strip(" ,|()-–—") for x in _protect(part).split(",")] if not parse_location(part.strip(" ,|()-–—")) else [part.strip(" ,|()-–—")]:
                p = p.replace("\x00", ", ")
                if not p or re.fullmatch(r"(expected|graduated|class of)", p, re.I):
                    continue
                if INSTITUTION_WORDS.search(p):
                    if cur and cur["institution"]:
                        push()
                        cur = None
                    cur = cur or {"institution": "", "degree": "", "location": "", "end": "", "details": []}
                    cur["institution"] = p
                elif DEGREE_WORDS.search(p) and not (cur and cur["degree"] and cur["institution"]):
                    cur = cur or {"institution": "", "degree": "", "location": "", "end": "", "details": []}
                    cur["degree"] = cur["degree"] or p
                elif cur and not cur["location"] and parse_location(p):
                    cur["location"] = p
                elif cur:
                    cur["details"].append(p)
        if cur and year and not cur["end"]:
            cur["end"] = "expected " + year if re.search(r"expected", line, re.I) else year
    push()
    return out


def parse_skills(lines):
    groups = {}
    for line, _ in lines:
        m = re.match(r"^([A-Z][\w &/+-]{1,40}?)\s*:\s*(.+)$", line)
        group, items = (m.group(1).strip(), m.group(2)) if m else ("Skills", line)
        parts = [p.strip(" .") for p in re.split(r"\s*[,;|•·]\s*|\s+/\s+", items)]
        bucket = groups.setdefault(group, [])
        for p in parts:
            if p and len(p) <= 60 and p.lower() not in (x.lower() for x in bucket):
                bucket.append(p)
    return [{"group": g, "items": items} for g, items in groups.items() if items]


def parse_certs(lines):
    out = []
    for line, _ in lines:
        years = YEAR_RE.findall(line)
        rest = YEAR_RE.sub("", line).strip(" ,()-–—|")
        parts = [p.strip(" ,()") for p in re.split(r"\s+[—–|-]\s+|,\s+", rest) if p.strip(" ,()")]
        if parts:
            out.append({"name": parts[0], "issuer": ", ".join(parts[1:]), "year": years[-1] if years else ""})
    return out


def classify(secs, text):
    if {"experience", "education", "skills"} & set(secs):
        return "resume"
    if re.search(r"^\s*(dear\b|to the hiring)", text, re.I | re.M) or re.search(r"\b(sincerely|regards),?\s*$", text, re.I | re.M):
        return "letter"
    return "other"


def parse_document(text):
    """One document's text → (kind, partial profile, notes)."""
    secs = sections(lines_of(text))
    kind = classify(secs, text)
    if kind != "resume":
        return kind, {}, []
    contact, notes = parse_header(secs["header"], text)
    draft = {"contact": {k: v for k, v in contact.items() if k in prof.CONTACT_KEYS},
             "headline": contact.get("headline", ""),
             "summary": " ".join(l for l, _ in secs.get("summary", [])),
             "links": links_in(text, [l for l, _ in secs["header"]])}
    roles, role_notes = parse_roles(secs.get("experience", []))
    draft["experience"] = roles
    draft["education"] = parse_education(secs.get("education", []))
    draft["skills"] = parse_skills(secs.get("skills", []))
    draft["certifications"] = parse_certs(secs.get("certifications", []))
    return kind, draft, notes + role_notes


# ---- merging -------------------------------------------------------------------------------

def _k(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _date_key(v):
    v = (v or "").lower()
    return "9999-99" if v == "present" else v.replace("expected ", "") or "0000"


def merge(found, structured):
    """Combine per-file drafts. Structured profile data wins; extraction only fills its gaps."""
    draft = prof.skeleton()
    conflicts = []
    seen_contact = {}
    for src, d in found:
        for k, v in d.get("contact", {}).items():
            if not v:
                continue
            if not draft["contact"][k]:
                draft["contact"][k], seen_contact[k] = v, src
            elif _k(draft["contact"][k]) != _k(v):
                conflicts.append(f"contact.{k}: used {draft['contact'][k]!r} ({seen_contact[k]}); "
                                 f"{src} has {v!r}")
        for k in ("summary", "headline"):
            if d.get(k) and not draft[k]:
                draft[k] = d[k]
        for k, v in d.get("links", {}).items():
            if k == "other":
                draft["links"]["other"] += [x for x in v if x not in draft["links"]["other"]]
            elif v and not draft["links"][k]:
                draft["links"][k] = v
        for role in d.get("experience", []):
            key = (_k(role["employer"]), _k(role["title"])) if role["employer"] else ("", _k(role["title"]), role["start"])
            same = next((r for r in draft["experience"] if r["_key"] == key), None)
            if same:
                same["bullets"] += [b for b in role["bullets"] if _k(b) not in {_k(x) for x in same["bullets"]}]
                for f in ("start", "end", "location"):
                    if len(role[f]) > len(same[f]):
                        same[f] = role[f]
            else:
                draft["experience"].append({**role, "bullets": list(role["bullets"]), "_key": key})
        for e in d.get("education", []):
            if not any(_k(x["institution"]) == _k(e["institution"]) and _k(x["degree"]) == _k(e["degree"])
                       for x in draft["education"]):
                draft["education"].append(e)
        for g in d.get("skills", []):
            same = next((x for x in draft["skills"] if _k(x["group"]) == _k(g["group"])), None)
            if same:
                same["items"] += [i for i in g["items"] if _k(i) not in {_k(x) for x in same["items"]}]
            else:
                draft["skills"].append({"group": g["group"], "items": list(g["items"])})
        for c in d.get("certifications", []):
            if not any(_k(x["name"]) == _k(c["name"]) for x in draft["certifications"]):
                draft["certifications"].append(c)
    for r in draft["experience"]:
        r.pop("_key", None)
    draft["experience"].sort(key=lambda r: (_date_key(r["end"]), _date_key(r["start"])), reverse=True)
    draft["education"].sort(key=lambda e: _date_key(e["end"]), reverse=True)

    for s in structured:  # structured data takes precedence, field by field
        for key, val in s.items():
            if isinstance(val, dict) and isinstance(draft.get(key), dict):
                for k, v in val.items():
                    if v not in (None, "", [], {}):
                        if isinstance(v, dict) and isinstance(draft[key].get(k), dict):
                            draft[key][k].update({a: b for a, b in v.items() if b not in (None, "")})
                        else:
                            draft[key][k] = v
            elif val not in (None, "", [], {}):
                draft[key] = val
    return prof.normalize(draft), conflicts


# ---- report --------------------------------------------------------------------------------

OPTIONAL_FIELDS = {"contact.preferred_name", "contact.postal_code", "links.other"}


def empty_fields(draft):
    """Every field the draft could not ground, as dotted paths."""
    out = []
    for k, v in draft["contact"].items():
        if not prof.text(v):
            out.append(f"contact.{k}")
    for k in ("summary", "headline"):
        if not prof.text(draft.get(k)):
            out.append(k)
    for k, v in draft["links"].items():
        if not v:
            out.append(f"links.{k}")
    for sec in ("experience", "education", "skills", "certifications"):
        if not draft[sec]:
            out.append(f"{sec} (none found)")
    for i, r in enumerate(draft["experience"]):
        for k in ("employer", "title", "start", "end", "location"):
            if not prof.text(r.get(k)):
                out.append(f"experience[{i}].{k}")
        if not prof.bullets(r):
            out.append(f"experience[{i}].bullets")
    for i, e in enumerate(draft["education"]):
        for k in ("institution", "degree", "end"):
            if not prof.text(e.get(k)):
                out.append(f"education[{i}].{k}")
    return [f for f in out if f not in OPTIONAL_FIELDS]


def tilde(p):
    try:
        return "~/" + str(Path(p).resolve().relative_to(Path.home()))
    except ValueError:
        return str(p)


def ingest(root):
    """Return (draft, report_lines). Pure apart from reading the files under `root`."""
    root = Path(root).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"{root} does not exist")
    files = collect(root)
    base = root if root.is_dir() else root.parent
    found, structured, notes = [], [], []
    kinds = {"resume": [], "letter": [], "other": [], "structured": [], "skipped": []}
    for f in files:
        rel = str(f.relative_to(base))
        if f.suffix.lower() in STRUCTURED_TYPES:
            data = read_structured(f)
            if data is not None:
                problems = prof.validate(prof.normalize(data))
                if problems:
                    raise ValueError(f"{rel} looks like a profile but is invalid: " + "; ".join(problems))
                structured.append(data)
                kinds["structured"].append(rel)
            continue
        try:
            text = read_text(f)
        except MissingReader as e:
            kinds["skipped"].append(f"{rel} ({e})")
            continue
        except (OSError, zipfile.BadZipFile, KeyError, ValueError) as e:
            kinds["skipped"].append(f"{rel} (unreadable: {type(e).__name__})")
            continue
        if not text.strip():
            kinds["skipped"].append(f"{rel} (no extractable text — a scanned image?)")
            continue
        kind, draft, doc_notes = parse_document(text)
        kinds[kind].append(rel)
        if draft:
            found.append((rel, draft))
            notes += [f"{rel}: {n}" for n in doc_notes]
    draft, conflicts = merge(found, structured)
    missing = empty_fields(draft)
    r = [f"Read {len(files)} file(s) from {tilde(root)}"]
    labels = {"structured": "structured profile data (takes precedence)", "resume": "resumes (facts extracted)",
              "letter": "cover letters (style reference only; no facts taken)",
              "other": "other documents (style reference only; no facts taken)", "skipped": "skipped"}
    for k, label in labels.items():
        if kinds[k]:
            r.append(f"  {label}: " + ", ".join(kinds[k]))
    ex = draft["experience"]
    r.append(f"Found: {len(ex)} role(s), {sum(len(prof.bullets(x)) for x in ex)} bullet(s), "
             f"{len(draft['education'])} education, {sum(len(g.get('items') or []) for g in draft['skills'])} "
             f"skill(s), {len(draft['certifications'])} certification(s)")
    if ex and not structured:
        r.append(f"  All {len(ex)} extracted role(s) are marked core: true (always shown). "
                 f"Set core: false on any the resume may drop.")
    if conflicts or notes:
        r.append("Check these:")
        r += [f"  - {x}" for x in conflicts + notes]
    if missing:
        r.append("Needs your input (not found in your files; left empty — never guessed):")
        r += [f"  - {m}" for m in missing]
    empty_answers = [k for k in prof.ANSWER_KEYS if not prof.text(draft["answers"].get(k))] + \
        [f"eeo.{k}" for k in prof.EEO_KEYS if not prof.text(draft["answers"]["eeo"].get(k))]
    if empty_answers:
        r.append("  - answers." + ", answers.".join(empty_answers) +
                 " (never extracted; fill them in, or the bot asks you when a form needs one)")
    return draft, r


def dump(draft, root):
    import yaml
    head = (f"# DRAFT profile generated by ingest_profile.py from {tilde(root)}.\n"
            f"# Review it once: everything here is what the kit may claim about you.\n"
            f"# Empty fields were not found in your files — fill them in or leave them empty.\n")
    return head + yaml.safe_dump(draft, sort_keys=False, allow_unicode=True, width=100)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Draft profile.yaml from a folder of your own documents.")
    ap.add_argument("source", help="a folder (walked recursively) or a single file")
    ap.add_argument("--out", default=str(prof.DEFAULT_PROFILE), help="draft path, or - for stdout (default: %(default)s)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing, different profile")
    args = ap.parse_args(argv)
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("error: PyYAML is required: python3 -m pip install --user pyyaml", file=sys.stderr)
        return 1
    try:
        draft, report = ingest(args.source)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    text = dump(draft, args.source)
    if args.out == "-":
        sys.stdout.write(text)
        print("\n".join(report), file=sys.stderr)
        return 0
    out = Path(args.out).expanduser()
    if out.exists() and out.read_text(encoding="utf-8") != text and not args.force:
        print(f"error: {tilde(out)} exists and differs from this draft (it may hold your reviewed "
              f"edits). Pass --force to overwrite it, or --out another path.", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print("\n".join(report))
    print(f"Wrote draft: {tilde(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
