import copy
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_resume as br  # noqa: E402
import profile as prof  # noqa: E402

EXAMPLE = ROOT / "examples/example_profile.yaml"
TEMPLATE = ROOT / "templates/resume.html"


def build(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts/build_resume.py"), *map(str, args)],
                          capture_output=True, text=True)


def write_profile(tmp_path, doc):
    p = tmp_path / "profile.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


def example():
    return yaml.safe_load(EXAMPLE.read_text())


def pdf_text(path):
    try:
        import pypdf
        return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(str(path)).pages)
    except ImportError:
        pass
    if shutil.which("pdftotext"):
        return subprocess.run(["pdftotext", str(path), "-"], capture_output=True, text=True).stdout
    pytest.skip("no PDF text extractor (pip install pypdf, or poppler's pdftotext) to read the PDF back")


def have_renderer():
    if br.find_chrome():
        return True
    try:
        import weasyprint  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not have_renderer(), reason="no Chrome/Chromium and no WeasyPrint: cannot render a PDF")
def test_renders_a_real_pdf_from_the_example(tmp_path):
    out = tmp_path / "app" / "resume.pdf"
    r = build("--profile", EXAMPLE, "--template", TEMPLATE, "--out", out)
    assert r.returncode == 0, r.stderr
    assert br.is_pdf(out) and br.page_count(out) >= 1
    assert ("chrome" if br.find_chrome() else "weasyprint") in r.stdout
    text = " ".join(pdf_text(out).split())
    assert "Robin Testwell" in text
    # a full page of content: every role and section made it into the PDF
    for s in ("Bramblecone Health Analytics", "Quillfeather Logistics", "Western Plains State University",
              "Cloud Data Engineer Professional"):
        assert s in text
    assert len(text.split()) > 250
    filled = out.with_suffix(".html").read_text()
    assert "{{" not in filled


def test_every_bullet_is_verbatim_from_the_profile():
    doc = prof.load_profile(EXAMPLE)
    out = br.build_html(doc, TEMPLATE.read_text())
    verified = {b for r in doc["experience"] for b in prof.bullets(r)} | \
               {d for e in doc["education"] for d in e["details"]}
    items = [html.unescape(x) for x in re.findall(r"<li>(.*?)</li>", out, re.S)]
    assert items and all(i in verified for i in items)
    assert len(items) == len(verified)


def test_missing_core_role_fails_loudly(tmp_path):
    doc = example()
    doc["experience"][1]["bullets"] = []  # a core role with nothing verified to show
    r = build("--profile", write_profile(tmp_path, doc), "--template", TEMPLATE, "--out", tmp_path / "r.pdf",
              "--html-only")
    assert r.returncode != 0
    assert "Data Engineer at Quillfeather Logistics" in r.stderr and "core" in r.stderr
    assert not (tmp_path / "r.html").exists()


def test_tailoring_selects_never_rewrites(tmp_path):
    doc = prof.load_profile(EXAMPLE)
    warnings = []
    sel = {"roles": {"r0": ["r0b3", "r0b0", "r0b99"], "r1": ["r1b2"]},  # r2 (non-core) dropped
           "summary": "Known for turning brittle nightly jobs into observable, tested systems and for "
                      "documentation that other teams actually use."}
    out = br.build_html(doc, TEMPLATE.read_text(), sel, warnings.append)
    items = [html.unescape(x) for x in re.findall(r"<li>(.*?)</li>", out)]
    r0, r1 = prof.bullets(doc["experience"][0]), prof.bullets(doc["experience"][1])
    assert items[:2] == [r0[3], r0[0]]          # the chosen order
    assert items[2:4] == [r1[2], r1[0]]         # topped up to two bullets, from verified text
    assert "Lumen &amp; Ledger" not in out      # non-core role may be dropped
    assert "Data engineer with eight years" not in out and "Known for turning" in out
    assert any("r0b99" in w for w in warnings)

    # a rewritten summary is refused in favour of the verified one
    warnings.clear()
    out = br.build_html(doc, TEMPLATE.read_text(), {"roles": {"r0": [], "r1": []},
                                                    "summary": "World-class engineer."}, warnings.append)
    assert "World-class" not in out and "Data engineer with eight years" in out
    assert any("summary" in w for w in warnings)

    # dropping a core role fails loudly, naming it
    with pytest.raises(br.BuildError, match="Senior Data Engineer at Bramblecone Health Analytics"):
        br.build_html(doc, TEMPLATE.read_text(), {"roles": {"r1": []}}, warnings.append)


def test_jd_uses_the_resume_slot(tmp_path, slot_config, llm_stub):
    llm_stub.replies = [json.dumps({"roles": {"r0": ["r0b1", "r0b0"], "r1": ["r1b0", "r1b1"]}})]
    jd = tmp_path / "jd.json"
    jd.write_text(json.dumps({"title": "Data Engineer", "company": "Example Co", "description": "Kafka."}))
    r = build("--profile", EXAMPLE, "--template", TEMPLATE, "--out", tmp_path / "r.pdf", "--html-only",
              "--jd", jd, "--config", slot_config)
    assert r.returncode == 0, r.stderr
    assert llm_stub.models == ["m-resume"]
    assert "Lumen" not in (tmp_path / "r.html").read_text()


def test_unknown_tokens_warn_and_still_build(tmp_path):
    tpl = tmp_path / "mine.html"
    tpl.write_text(TEMPLATE.read_text().replace("<h1>{{FULL_NAME}}</h1>",
                                                "<h1>{{FULL_NAME}}</h1><p>{{FAVORITE_COLOUR}}</p>"))
    r = build("--profile", EXAMPLE, "--template", tpl, "--out", tmp_path / "r.pdf", "--html-only",
              "--warn-unknown-tokens")
    assert r.returncode == 0, r.stderr
    assert "unknown token(s): FAVORITE_COLOUR" in r.stderr
    assert re.search(r"mine\.html:\d+: \{\{FAVORITE_COLOUR\}\}", r.stderr)
    out = (tmp_path / "r.html").read_text()
    assert "{{FAVORITE_COLOUR}}" in out and "Robin Testwell" in out  # left visible, not silently dropped


def test_empty_optional_section_is_removed(tmp_path):
    doc = example()
    doc["certifications"] = []
    doc["summary"] = ""
    out = br.build_html(prof.normalize(doc), TEMPLATE.read_text())
    assert "<h2>Certifications</h2>" not in out and "<h2>Summary</h2>" not in out
    assert "<h2>Experience</h2>" in out and "<h2>Skills</h2>" in out


def test_no_renderer_fails_naming_both(tmp_path, monkeypatch):
    monkeypatch.setattr(br, "find_chrome", lambda: None)
    monkeypatch.setitem(sys.modules, "weasyprint", None)
    h = tmp_path / "x.html"
    h.write_text("<p>x</p>")
    with pytest.raises(br.BuildError, match="Chrome.*weasyprint"):
        br.render_pdf(h, tmp_path / "x.pdf")
