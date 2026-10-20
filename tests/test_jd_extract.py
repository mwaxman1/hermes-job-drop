import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import jd_extract as jd  # noqa: E402

# Local fixtures only — no network in tests. Fictional companies.
GREENHOUSE = """<!doctype html><html><head><title>Job Application for Data Engineer at Example Analytics</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",
 "title":"Senior Data Engineer","hiringOrganization":{"@type":"Organization","name":"Example Analytics"},
 "jobLocation":{"@type":"Place","address":{"addressLocality":"Lakeview","addressRegion":"CO","addressCountry":"US"}},
 "description":"&lt;p&gt;You will own our &lt;strong&gt;streaming pipelines&lt;/strong&gt;.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Kafka&lt;/li&gt;&lt;li&gt;dbt&lt;/li&gt;&lt;/ul&gt;"}
</script></head><body><nav>Jobs home</nav><h1>Senior Data Engineer</h1><div id="content">...</div>
<form id="application_form"></form></body></html>"""

LEVER = """<html><head><title>Example Freight - Operations Analyst</title>
<meta property="og:title" content="Example Freight - Operations Analyst"></head>
<body><div class="posting-headline"><h2>Operations Analyst</h2></div>
<div class="section"><h3>About the role</h3><p>Own the weekly capacity report.</p>
<ul><li>SQL</li><li>Excel</li></ul></div><a href="/example-freight/abc/apply">Apply for this job</a></body></html>"""

CAREERS_GH_EMBED = """<html><head><title>Careers | Example Robotics</title>
<meta property="og:site_name" content="Example Robotics"></head><body><h1>Firmware Engineer</h1>
<p>Build motor control firmware.</p>
<script src="https://boards.greenhouse.io/embed/job_board/js?for=examplerobotics"></script></body></html>"""

CAREERS_ASHBY_LINK = """<html><head><title>Product Designer — Example Studio</title></head><body>
<h1>Product Designer</h1><p>Design our tools.</p>
<a href="https://jobs.ashbyhq.com/examplestudio/a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d">Apply</a></body></html>"""

CLOSED = """<html><head><title>Example Co careers</title></head><body><h1>Backend Engineer</h1>
<p>This job is no longer accepting applications.</p></body></html>"""


def test_greenhouse_json_ld():
    out = jd.parse(GREENHOUSE, "https://job-boards.greenhouse.io/exampleanalytics/jobs/40123")
    assert out["title"] == "Senior Data Engineer" and out["company"] == "Example Analytics"
    assert out["location"] == "Lakeview, CO, US"
    assert "streaming pipelines" in out["description"] and "- Kafka" in out["description"]
    assert out["ats"] == "greenhouse" and out["source"] == "json-ld"
    assert out["apply_url"] == "https://job-boards.greenhouse.io/exampleanalytics/jobs/40123"  # inline form
    assert out["closed"] is False


def test_lever_title_and_apply_url():
    out = jd.parse(LEVER, "https://jobs.lever.co/example-freight/abc")
    assert out["ats"] == "lever" and out["apply_url"] == "https://jobs.lever.co/example-freight/abc/apply"
    assert out["title"] == "Operations Analyst" and out["company"] == "Example Freight"
    assert "Own the weekly capacity report." in out["description"]


def test_company_page_embedding_an_ats():
    out = jd.parse(CAREERS_GH_EMBED, "https://www.example.com/careers?gh_jid=40999")
    assert out["ats"] == "greenhouse"
    assert out["apply_url"] == "https://job-boards.greenhouse.io/examplerobotics/jobs/40999"
    assert out["company"] == "Example Robotics" and out["title"] == "Firmware Engineer"

    out = jd.parse(CAREERS_ASHBY_LINK, "https://example.com/jobs/designer")
    assert out["ats"] == "ashby"
    assert out["apply_url"].endswith("/a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d/application")
    assert out["title"] == "Product Designer" and out["company"] == "Example Studio"


def test_ats_detection_and_closed():
    cases = {
        "https://example.wd5.myworkdayjobs.com/External/job/Remote/Analyst_R123": "workday",
        "https://jobs.smartrecruiters.com/ExampleCo/123": "smartrecruiters",
        "https://careers-example.icims.com/jobs/123/analyst/job": "icims",
        "https://example.dayforcehcm.com/CandidatePortal/en-US/example/Posting/View/1": "dayforce",
        "https://example.avature.net/careers/JobDetail/1": "avature",
        "https://example.com/jobs/1": "unknown",
    }
    for url, ats in cases.items():
        assert jd.detect_ats(url) == ats, url
    assert jd.parse(CLOSED, "https://example.com/jobs/9")["closed"] is True


def test_cli_with_saved_html(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(GREENHOUSE)
    out = tmp_path / "jd.json"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/jd_extract.py"),
                        "https://boards.greenhouse.io/exampleanalytics/jobs/40123", "--html", str(page),
                        "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(out.read_text())["company"] == "Example Analytics"
