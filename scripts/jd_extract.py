#!/usr/bin/env python3
"""Fetch a job posting and pull out what the run needs.

    python3 scripts/jd_extract.py URL [--out jd.json]
    python3 scripts/jd_extract.py URL --html saved_page.html     # parse a saved page, no network

Prints JSON: url, title, company, location, description (plain text), ats, apply_url
(the page that actually holds the form), closed (posting gone / not accepting applications).
Sources, best first: schema.org JobPosting JSON-LD, OpenGraph/<title>, the page text.
"""
import argparse
import html as htmllib
import json
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"

# (ats, host regex). Checked against the posting URL, then against ATS links/iframes in the page.
ATS_HOSTS = [
    ("greenhouse", r"(^|\.)greenhouse\.io$"),
    ("lever", r"(^|\.)lever\.co$"),
    ("ashby", r"(^|\.)ashbyhq\.com$"),
    ("workday", r"(^|\.)myworkdayjobs\.com$|(^|\.)myworkdaysite\.com$"),
    ("smartrecruiters", r"(^|\.)smartrecruiters\.com$"),
    ("icims", r"(^|\.)icims\.com$"),
    ("dayforce", r"(^|\.)dayforcehcm\.com$"),
    ("avature", r"(^|\.)avature\.net$"),
    ("workable", r"(^|\.)workable\.com$"),
    ("bamboohr", r"(^|\.)bamboohr\.com$"),
    ("jobvite", r"(^|\.)jobvite\.com$"),
]
CLOSED_RE = re.compile(
    r"no longer (accepting applications|available|open|active)|position (has been|is) (filled|closed)"
    r"|this (job|posting|position|role) (has )?(expired|closed|been removed)|job not found"
    r"|posting (has )?closed|not accepting applications", re.I)


def detect_ats(url):
    host = (urlsplit(url).hostname or "").lower()
    for ats, rx in ATS_HOSTS:
        if re.search(rx, host):
            return ats
    return "unknown"


def apply_url(url, ats):
    """The URL of the page that holds the application form for a posting URL."""
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"
    if ats == "ashby" and not base.endswith("/application"):
        return base + "/application"
    if ats == "lever" and not base.endswith("/apply"):
        return base + "/apply"
    if ats == "workable" and "/j/" in base and not base.endswith("/apply"):
        return base + "/apply/"
    if ats == "jobvite" and "/job/" in base and not base.endswith("/apply"):
        return base + "/apply"
    return url  # greenhouse is inline; wizard-style portals start at the posting


class _Page(HTMLParser):
    """Collects visible text, JSON-LD blocks, meta tags, <title>, <h1>, and links/iframes."""
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section",
             "article", "header", "footer", "table", "dd", "dt", "blockquote", "pre"}
    SKIP = {"script", "style", "noscript", "template", "svg", "nav", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.ldjson, self.meta, self.links = [], [], {}, []
        self.title = self.h1 = ""
        self._skip = 0
        self._in = None
        self._ld = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and "ld+json" in (a.get("type") or ""):
            self._ld = []
        if tag in self.SKIP:
            self._skip += 1
        if tag == "meta":
            k = a.get("property") or a.get("name")
            if k and a.get("content"):
                self.meta.setdefault(k.lower(), a["content"])
        if tag in ("a", "iframe") and (a.get("href") or a.get("src")):
            self.links.append(a.get("href") or a.get("src"))
        if tag in ("title", "h1"):
            self._in = tag
        if tag in self.BLOCK:
            self.text.append("\n")
        if tag == "li":
            self.text.append("- ")

    def handle_endtag(self, tag):
        if tag == "script" and self._ld is not None:
            self.ldjson.append("".join(self._ld))
            self._ld = None
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == self._in:
            self._in = None
        if tag in self.BLOCK:
            self.text.append("\n")

    def handle_data(self, data):
        if self._ld is not None:
            self._ld.append(data)
            return
        if self._in == "title":
            self.title += data
        elif self._in == "h1" and not self._skip:
            self.h1 += data
        if not self._skip:
            self.text.append(data)


def html_to_text(fragment):
    p = _Page()
    p.feed(fragment)
    return clean_text("".join(p.text))


def clean_text(s):
    lines = [" ".join(line.split()) for line in s.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _job_postings(blocks):
    for raw in blocks:
        try:
            data = json.loads(raw.strip())
        except ValueError:
            continue
        stack = [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
            elif isinstance(d, dict):
                t = d.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    yield d
                stack.extend(d.get("@graph", []) if isinstance(d.get("@graph"), list) else [])


def _ld_location(jp):
    locs = jp.get("jobLocation")
    locs = locs if isinstance(locs, list) else [locs] if locs else []
    out = []
    for loc in locs:
        addr = (loc or {}).get("address") if isinstance(loc, dict) else None
        if isinstance(addr, dict):
            out.append(", ".join(str(addr[k]) for k in ("addressLocality", "addressRegion", "addressCountry")
                                 if isinstance(addr.get(k), str) and addr.get(k)))
        elif isinstance(addr, str):
            out.append(addr)
    if jp.get("jobLocationType") == "TELECOMMUTE":
        out.append("Remote")
    return "; ".join(x for x in out if x)


def _company_from_titles(titles, ats, on_ats):
    """Company from page titles: 'Job Application for X at Y', or lever's 'Company - Role'."""
    for t in titles:
        m = re.match(r"(?:Job Application for )?.+? at (.+?)(?: [|–—-] .*)?$", t)
        if m:
            return m.group(1)
    for t in titles:
        if ats == "lever":
            m = re.match(r"(.+?) [-–—|] .+$", t)
            if m:
                return m.group(1)
        elif not on_ats:  # a company's own site: "Role — Company". On ATS pages the dash part is
            m = re.match(r".+? [-–—|] (.+)$", t)  # often a location ("Role - France"), so skip it
            if m:
                return m.group(1)
    return ""


def _title_from_titles(titles, ats):
    for t in titles:
        m = re.match(r"(?:Job Application for )?(.+?) at .+$", t) or (
            re.match(r".+? [-–—|] (.+)$", t) if ats == "lever" else re.match(r"(.+?) [-–—|@] .+$", t))
        if m:
            return m.group(1)
    return titles[0] if titles else ""


def _org_slug(url, ats):
    parts = [p for p in urlsplit(url).path.split("/") if p]
    if ats in ("greenhouse", "lever", "ashby") and parts:
        return parts[0]
    return ""


def parse(page_html, url):
    """Extract the posting fields from HTML. Pure function — the tests call this directly."""
    p = _Page()
    p.feed(page_html)
    ats = detect_ats(url)
    form_url = url
    if ats == "unknown":  # company site: look for the ATS underneath (iframe, apply link, embed)
        for link in p.links:
            full = urljoin(url, htmllib.unescape(link))
            found = detect_ats(full)
            if found != "unknown":
                ats, form_url = found, full
                break
    gh_jid = parse_qs(urlsplit(url).query).get("gh_jid")
    if gh_jid and (ats in ("greenhouse", "unknown")):
        org = re.search(r"greenhouse\.io/(?:embed/job_board/js\?for=|embed/job_app\?for=)?([\w-]+)", page_html)
        ats = "greenhouse"
        if org and org.group(1) not in ("embed", "v1"):
            form_url = f"https://job-boards.greenhouse.io/{org.group(1)}/jobs/{gh_jid[0]}"

    out = {"url": url, "title": "", "company": "", "location": "", "description": "",
           "ats": ats, "apply_url": apply_url(form_url, ats), "closed": False, "source": ""}
    jp = next(_job_postings(p.ldjson), None)
    if jp:
        org = jp.get("hiringOrganization")
        out.update(
            title=str(jp.get("title") or "").strip(),
            company=str(org.get("name") if isinstance(org, dict) else org or "").strip(),
            location=_ld_location(jp),
            description=html_to_text(htmllib.unescape(str(jp.get("description") or ""))),
            source="json-ld")
    titles = [" ".join(htmllib.unescape(t).split()) for t in (p.title, p.meta.get("og:title", "")) if t.strip()]
    out["title"] = out["title"] or " ".join(p.h1.split()) or _title_from_titles(titles, ats)
    out["company"] = (out["company"] or p.meta.get("og:site_name", "").strip() or _company_from_titles(titles, ats, detect_ats(url) != "unknown")
                      or _org_slug(form_url, ats).replace("-", " ").title())
    page_text = clean_text("".join(p.text))
    if not out["description"]:
        out["description"] = page_text
        out["source"] = out["source"] or "page-text"
    out["closed"] = bool(CLOSED_RE.search(page_text[:5000])) and len(out["description"]) < 3000
    return out


def fetch(url, timeout=20):
    """(status, final_url, html). 404/410 come back as a status, not an exception."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            charset = r.headers.get_content_charset() or "utf-8"
            return r.status, r.geturl(), r.read().decode(charset, "replace")
    except urllib.error.HTTPError as e:
        return e.code, url, e.read().decode("utf-8", "replace")


def extract(url, page_html=None):
    if page_html is None:
        status, final, page_html = fetch(url)
        if status in (404, 410):
            return {"url": url, "title": "", "company": "", "location": "", "description": "",
                    "ats": detect_ats(url), "apply_url": url, "closed": True, "source": f"http-{status}"}
        if status >= 400:
            raise OSError(f"{url} answered HTTP {status}")
        if "error=true" in final:  # greenhouse redirects closed postings to the board with ?error=true
            out = parse(page_html, url)
            out["closed"] = True
            return out
    return parse(page_html, url)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Extract a job posting (title, company, text, ATS, apply URL).")
    ap.add_argument("url")
    ap.add_argument("--html", help="parse this saved HTML file instead of fetching")
    ap.add_argument("--out", help="write the JSON here as well as printing it")
    args = ap.parse_args(argv)
    try:
        page = open(args.html, encoding="utf-8").read() if args.html else None
        out = extract(args.url, page)
    except (OSError, urllib.error.URLError, ValueError) as e:
        print(f"error: could not read the posting: {e}", file=sys.stderr)
        return 1
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
