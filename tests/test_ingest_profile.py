import importlib.util
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ingest_profile as ing  # noqa: E402
import profile as prof  # noqa: E402

# A synthetic persona (fictional names, 555-01xx phone). The PDF deliberately has NO email.
PDF_LINES = [
    "Avery Quinlan",
    "Platform Engineer",
    "+1 555 555 0177 · Riverbend, OR · linkedin.com/in/example-avery-quinlan · github.com/example-aq",
    "S U M M A RY",
    "Platform engineer with six years of experience running container platforms for product teams.",
    "EXPERIENCE",
    "Platform Engineer Mar 2022 – Present",
    "Driftwood Example Systems · Remote",
    "• Migrated 140 services from hand-built VMs to a managed container platform with no customer-facing",
    "downtime.",
    "• Cut average deploy time from 45 minutes to 6 minutes by rebuilding the CI pipeline.",
    "Site Reliability Engineer Jun 2019 – Feb 2022",
    "Harborlight Example Logistics · Riverbend, OR",
    "• Wrote the incident review process adopted across the engineering organization.",
    "• Reduced paging volume by 60% by tuning alert thresholds with the owning teams.",
    "EDUCATION",
    "Coastal Example University | B.S. Computer Engineering | 2019",
    "SKILLS",
    "Languages: Go, Python, Bash",
    "Infrastructure: Kubernetes, Terraform, Prometheus",
    "CERTIFICATIONS",
    "Certified Example Cloud Administrator — Example Cloud Academy, 2021",
]
LETTER = ["Dear Hiring Team,", "Please reply to the recruiter at recruiter@example.org about this.",
          "I have run platforms for six years.", "Sincerely,", "Avery Quinlan"]
NOTES_TXT = "Notes on a side project: a small static site generator I maintain on weekends.\n"


def make_pdf(path, lines):
    """A minimal, valid one-page PDF with real extractable text (WinAnsi Helvetica)."""
    def esc(s):
        return s.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    ops = b"".join(b"BT /F1 9 Tf 40 %d Td (" % (760 - 14 * i) + esc(t) + b") Tj ET\n" for i, t in enumerate(lines))
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R " % (612, 792) +
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(ops) + ops + b"endstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    Path(path).write_bytes(bytes(out))


def make_docx(path, paragraphs):
    """A minimal valid DOCX (readable by python-docx and by the stdlib fallback)."""
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:document {ns}><w:body>{body}</w:body></w:document>')


def have_pdf_reader():
    return any(importlib.util.find_spec(m) for m in ("pypdf", "pdfplumber")) or bool(shutil.which("pdftotext"))


needs_pdf = pytest.mark.skipif(not have_pdf_reader(), reason="no PDF reader (pip install pypdf, or poppler's pdftotext)")


@pytest.fixture
def career(tmp_path):
    d = tmp_path / "career"
    (d / "letters").mkdir(parents=True)
    make_pdf(d / "resume.pdf", PDF_LINES)
    make_docx(d / "letters" / "cover_letter.docx", LETTER)
    (d / "notes.txt").write_text(NOTES_TXT)
    return d


def run_main(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts/ingest_profile.py"), *map(str, args)],
                          capture_output=True, text=True)


@needs_pdf
def test_mixed_folder_extracts_and_never_invents(career, tmp_path):
    out = tmp_path / "profile.yaml"
    r = run_main(career, "--out", out)
    assert r.returncode == 0, r.stderr
    d = yaml.safe_load(out.read_text())
    assert prof.validate(d) == []
    c = d["contact"]
    assert (c["first_name"], c["last_name"]) == ("Avery", "Quinlan")
    assert c["phone"] == "+1 555 555 0177"
    assert (c["city"], c["state"]) == ("Riverbend", "OR")
    # NEVER invent: no email in the resume → empty, and the report says so. The cover letter's
    # address belongs to someone else and must not be used.
    assert c["email"] == ""
    assert "contact.email" in r.stdout and "recruiter" not in out.read_text()
    assert d["headline"] == "Platform Engineer"
    assert d["summary"].startswith("Platform engineer with six years")
    roles = d["experience"]
    assert [(x["title"], x["employer"], x["start"], x["end"], x["location"]) for x in roles] == [
        ("Platform Engineer", "Driftwood Example Systems", "2022-03", "present", "Remote"),
        ("Site Reliability Engineer", "Harborlight Example Logistics", "2019-06", "2022-02", "Riverbend, OR"),
    ]
    assert roles[0]["bullets"][0] == ("Migrated 140 services from hand-built VMs to a managed container "
                                      "platform with no customer-facing downtime.")
    assert len(roles[1]["bullets"]) == 2 and all(x["core"] is True for x in roles)
    assert d["education"] == [{"institution": "Coastal Example University", "degree": "B.S. Computer Engineering",
                               "location": "", "end": "2019", "details": []}]
    assert {g["group"]: g["items"] for g in d["skills"]} == {
        "Languages": ["Go", "Python", "Bash"], "Infrastructure": ["Kubernetes", "Terraform", "Prometheus"]}
    assert d["certifications"] == [{"name": "Certified Example Cloud Administrator",
                                    "issuer": "Example Cloud Academy", "year": "2021"}]
    assert d["links"]["linkedin"] == "https://linkedin.com/in/example-avery-quinlan"
    assert d["links"]["github"] == "https://github.com/example-aq"
    # the report names what it used and every field it could not ground
    assert "resumes (facts extracted): resume.pdf" in r.stdout
    assert "cover letters (style reference only" in r.stdout and "letters/cover_letter.docx" in r.stdout
    assert "notes.txt" in r.stdout
    for field in ("contact.country", "contact.work_authorization", "answers.salary_expectation"):
        assert field in r.stdout


@needs_pdf
def test_idempotent(career, tmp_path):
    out = tmp_path / "p.yaml"
    assert run_main(career, "--out", out).returncode == 0
    first = out.read_bytes()
    r = run_main(career, "--out", out)  # same input, same draft: no --force needed
    assert r.returncode == 0, r.stderr
    assert out.read_bytes() == first
    assert ing.dump(ing.ingest(career)[0], career) == first.decode()


def test_comma_separated_role_heading_is_not_read_as_a_location():
    """'Senior Software Engineer, Northwind Systems' is a TITLE + EMPLOYER pair.

    Regression: LOCATION_RE matched the whole heading as city='Senior Software Engineer',
    region='Northwind Systems', so split_head consumed it as a location and the role came
    back with an empty title and an empty employer — silently, since the ambiguity note
    only fires when the pair cannot be split at all.
    """
    head = ["Senior Software Engineer, Northwind Systems, March 2021 - Present"]
    start, end, location, parts = ing.split_head(head)
    assert location == "", "the heading was swallowed as a location"
    title, employer, ambiguous = ing.assign_title_employer(parts)
    assert title == "Senior Software Engineer"
    assert employer == "Northwind Systems"
    assert not ambiguous
    assert (start, end) == ("2021-03", "present")


def test_a_real_city_state_pair_is_still_read_as_a_location():
    """The fix must not break the real case: 'Riverbend, OR' IS a location."""
    assert ing.parse_location("Riverbend, OR") is not None
    assert ing.parse_location("Austin, TX 78701") is not None


def test_never_overwrites_a_reviewed_profile_without_force(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "cv.md").write_text("# Sam Example\n\n## Skills\n\nPython, SQL\n")
    out = tmp_path / "profile.yaml"
    out.write_text("# my reviewed edits\n")
    r = run_main(src, "--out", out)
    assert r.returncode == 1 and "--force" in r.stderr and out.read_text() == "# my reviewed edits\n"
    assert run_main(src, "--out", out, "--force").returncode == 0


def test_structured_profile_takes_precedence(tmp_path):
    d = tmp_path / "career"
    d.mkdir()
    example = (ROOT / "examples/example_profile.yaml").read_text()
    (d / "profile.yaml").write_text(example)
    (d / "old_resume.md").write_text(
        "# Someone Else\nsomeone.else@example.com\n\n## Experience\n\nCook | Example Diner | 2001 - 2003\n"
        "- Made 400 omelettes a day for the breakfast crowd, every weekday.\n")
    draft, report = ing.ingest(d)
    expected = prof.normalize(yaml.safe_load(example))
    assert draft == expected  # used as-is: the structured file wins every field it sets
    assert any("structured profile data (takes precedence): profile.yaml" in line for line in report)


def test_missing_pdf_reader_skips_with_a_message(tmp_path, monkeypatch):
    d = tmp_path / "career"
    d.mkdir()
    make_pdf(d / "resume.pdf", PDF_LINES)
    (d / "cv.txt").write_text("Jo Example\njo@example.com\n\nSKILLS\nPython\n")
    for mod in ("pypdf", "pdfplumber"):
        monkeypatch.setitem(sys.modules, mod, None)  # import → ImportError
    monkeypatch.setattr(ing.shutil, "which", lambda name: None)
    draft, report = ing.ingest(d)
    text = "\n".join(report)
    assert "skipped: resume.pdf (no PDF reader: python3 -m pip install --user pypdf)" in text
    assert draft["contact"]["email"] == "jo@example.com"


def test_other_layouts_markdown_and_html(tmp_path):
    d = tmp_path / "career"
    d.mkdir()
    (d / "resume.md").write_text(
        "# Casey Example\n\ncasey@example.com | (555) 555-0123 | Port Example, ME\n\n"
        "## Professional Experience\n\n"
        "**Example Freight Co** — Operations Analyst — Jan 2020 to Present\n\n"
        "- Built the weekly capacity report used by four regional managers.\n"
        "- Cut manual data entry by 12 hours a week with shared intake templates.\n\n"
        "Junior Analyst, Example Freight Co, 06/2018 - 12/2019\n\n"
        "* Reconciled carrier invoices across three billing systems.\n\n"
        "## Education\n\nB.A. Economics, Example State College, 2018\n\n"
        "## Technical Skills\n\nExcel, SQL, Tableau\n")
    (d / "site.html").write_text(
        "<html><body><h1>Casey Example</h1><p>Analyst</p><a href='https://www.linkedin.com/in/example-casey'>me</a>"
        "<h2>Skills</h2><ul><li>Looker</li><li>SQL</li></ul></body></html>")
    draft, _ = ing.ingest(d)
    roles = draft["experience"]
    assert [(r["title"], r["employer"], r["start"], r["end"]) for r in roles] == [
        ("Operations Analyst", "Example Freight Co", "2020-01", "present"),
        ("Junior Analyst", "Example Freight Co", "2018-06", "2019-12"),
    ]
    assert roles[0]["bullets"][1] == "Cut manual data entry by 12 hours a week with shared intake templates."
    assert draft["contact"]["email"] == "casey@example.com"
    assert draft["contact"]["phone"] == "(555) 555-0123"
    assert draft["education"][0]["degree"] == "B.A. Economics"
    assert draft["education"][0]["institution"] == "Example State College"
    assert draft["links"]["linkedin"] == "https://www.linkedin.com/in/example-casey"  # from an href only
    skills = {i for g in draft["skills"] for i in g["items"]}
    assert {"Excel", "SQL", "Tableau", "Looker"} <= skills


def test_docx_stdlib_fallback(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "docx", None)
    p = tmp_path / "x.docx"
    make_docx(p, ["Hello there", "Second para"])
    assert ing.read_docx(p) == "Hello there\nSecond para"
