import copy
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import field_matching as fm  # noqa: E402
import profile as prof  # noqa: E402

EXAMPLE = ROOT / "examples/example_profile.yaml"


def test_shipped_template_and_example_validate():
    tpl = yaml.safe_load((ROOT / "templates/master_profile.template.yaml").read_text())
    assert prof.validate(tpl) == []
    # the template carries exactly the schema's keys, so ingestion drafts match it
    assert set(tpl) == set(prof.skeleton())
    assert set(tpl["contact"]) == set(prof.CONTACT_KEYS)
    assert set(tpl["experience"][0]) == set(prof.ROLE_KEYS)
    doc = prof.load_profile(EXAMPLE)
    assert prof.readiness(doc) == []


def test_invalid_shapes_are_named(tmp_path):
    doc = yaml.safe_load(EXAMPLE.read_text())
    bad = copy.deepcopy(doc)
    del bad["education"]
    bad["experience"][0]["bullets"] = "one string, not a list"
    bad["experience"][1]["core"] = "yes"
    bad["contact"]["email"] = ["a", "b"]
    problems = prof.validate(bad)
    assert "missing section `education`" in problems
    assert "experience[0].bullets must be a list of text" in problems
    assert "experience[1].core must be true or false" in problems
    assert "contact.email must be text" in problems
    p = tmp_path / "profile.yaml"
    p.write_text(yaml.safe_dump(bad))
    r = subprocess.run([sys.executable, str(ROOT / "scripts/profile.py"), "--profile", str(p)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "missing section `education`" in r.stderr


def test_readiness_and_helpers(tmp_path):
    doc = prof.load_profile(EXAMPLE)
    assert prof.full_name(doc) == "Robin Testwell"
    assert prof.contact_line(doc) == ("robin.testwell@example.com · +1 555 555 0142 · Lakeview, CO · "
                                      "linkedin.com/in/example-robin-testwell · github.com/example-robin-testwell · "
                                      "robin.example.com")
    empty = prof.normalize({"contact": {}, "experience": [{"employer": "X", "title": "Y", "bullets": []}]})
    assert prof.readiness(empty) == ["contact.first_name", "contact.last_name", "contact.email",
                                     "experience (at least one role with employer, title and a bullet)"]
    p = tmp_path / "p.yaml"
    p.write_text(yaml.safe_dump(empty))
    r = subprocess.run([sys.executable, str(ROOT / "scripts/profile.py"), "--profile", str(p), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "contact.email" in r.stderr


def test_field_matching_grounds_or_returns_empty():
    doc = prof.load_profile(EXAMPLE)
    cases = {
        "Legal First Name*": ("contact.first_name", "Robin"),
        "Surname": ("contact.last_name", "Testwell"),
        "Email address": ("contact.email", "robin.testwell@example.com"),
        "LinkedIn Profile URL": ("links.linkedin", "https://www.linkedin.com/in/example-robin-testwell"),
        "Website": ("links.portfolio", "https://robin.example.com"),
        "Current company": ("current_employer", "Bramblecone Health Analytics"),
        "How did you hear about us?": ("answers.how_did_you_hear", "Company careers page"),
        "Desired salary": ("answers.salary_expectation", ""),  # empty in the profile → not grounded
        "Favourite colour": (None, ""),
    }
    for label, (key, value) in cases.items():
        r = fm.resolve(label, doc)
        assert (r["key"], r["value"]) == (key, value), label
        assert r["grounded"] is bool(value)


def test_option_matching_never_picks_a_closest_guess():
    assert fm.match_option("decline", ["Male", "Female", "I don't wish to answer"]) == "I don't wish to answer"
    assert fm.match_option("Yes, I am authorized", ["Yes", "No"]) == "Yes"
    assert fm.match_option("remote", ["Remote (US)", "Onsite"]) == "Remote (US)"
    assert fm.match_option("Two weeks", ["Immediately", "1 month"]) is None
    assert fm.match_option("remote", ["Remote (US)", "Remote (EU)"]) is None  # ambiguous → park
    doc = prof.load_profile(EXAMPLE)
    r = fm.resolve("Gender", doc, ["Man", "Woman", "Decline to self-identify"])
    assert r["option"] == "Decline to self-identify" and r["grounded"]
