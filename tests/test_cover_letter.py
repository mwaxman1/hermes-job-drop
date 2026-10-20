import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_cover_letter as bcl  # noqa: E402
import profile as prof  # noqa: E402
from conftest import TEST_KEY  # noqa: E402

EXAMPLE = ROOT / "examples/example_profile.yaml"
TEMPLATE = ROOT / "templates/cover_letter.md"
JD = {"title": "Senior Data Engineer", "company": "Northwind Example Labs",
      "description": "We need a senior data engineer to make our streaming pipelines reliable, raise data "
                     "quality across teams, and keep warehouse costs in check. Python, Spark, Kafka, dbt."}

GOOD = {
    "GREETING": "Dear Northwind Example Labs hiring team,",
    "OPENING": "I am applying for the Senior Data Engineer role at Northwind Example Labs. Your posting asks "
               "for someone who can make streaming pipelines dependable and help other teams trust their "
               "data, and that has been the center of my work for eight years, most recently as a Senior "
               "Data Engineer at Bramblecone Health Analytics.",
    "BODY_PARA_1": "At Bramblecone I rebuilt the claims ingestion pipeline on an event-driven design, which cut "
                   "end-to-end latency from 26 hours to 40 minutes. I also introduced data contracts and schema "
                   "tests for 30+ upstream feeds, and broken dashboards went from a weekly event to fewer than "
                   "one per quarter. Those two changes speak directly to the reliability and data-quality "
                   "work your description puts first.",
    "BODY_PARA_2": "Your team also wants an engineer who raises the standard for the people around them. I led a "
                   "team of four engineers through a warehouse migration that finished two weeks early with "
                   "zero reporting downtime, wrote the on-call runbook and alerting standards that three other "
                   "engineering teams later adopted, and mentored two junior engineers to promotion within 18 "
                   "months. Before that, at Quillfeather Logistics, I cut monthly cloud spend by 31% by "
                   "partitioning hot tables and retiring unused jobs.",
    "BODY_PARA_3": "My daily tools are Python, SQL, Spark, Kafka, dbt and Airflow, which cover most of the stack "
                   "you list, and I hold the Cloud Data Engineer Professional certification.",
    "CLOSING": "I would welcome a conversation about how I could help Northwind Example Labs build pipelines "
               "that other teams can rely on. Thank you for your time and consideration.",
    "SIGNATURE": "Sincerely,\nRobin Testwell",
}


def doc():
    return prof.load_profile(EXAMPLE)


def run(tmp_path, slot_config, *extra):
    jd = tmp_path / "jd.json"
    jd.write_text(json.dumps(JD))
    out = tmp_path / "cover_letter.md"
    rc = bcl.main(["--profile", str(EXAMPLE), "--template", str(TEMPLATE), "--jd", str(jd),
                   "--out", str(out), "--config", str(slot_config), *extra])
    return rc, out


def test_good_letter_passes_every_gate():
    letter = bcl.render(TEMPLATE.read_text(), {**GOOD, "FULL_NAME": "Robin Testwell", "CONTACT_LINE": "x",
                                               "DATE": "May 1, 2026", "COMPANY": JD["company"],
                                               "ROLE_TITLE": JD["title"]})
    assert bcl.gate(GOOD, letter, doc(), JD, bcl.LEAK_TERMS) == []


def test_uses_the_cover_letter_slot_only(tmp_path, slot_config, llm_stub):
    llm_stub.replies = [json.dumps(GOOD)]
    rc, out = run(tmp_path, slot_config)
    assert rc == 0
    # six slots, six different models, all on the same server: only cover_letter's was called
    assert llm_stub.models == ["m-cover_letter"]
    assert llm_stub.requests[0][1] == f"Bearer {TEST_KEY}"
    letter = out.read_text()
    assert "{{" not in letter and "}}" not in letter
    assert letter.startswith("Robin Testwell\nrobin.testwell@example.com")
    assert "Re: Senior Data Engineer" in letter and letter.rstrip().endswith("Robin Testwell")
    # the model never sees fields it does not fill
    prompt = llm_stub.requests[0][2]["messages"][0]["content"]
    assert '"GREETING"' in prompt and '"FULL_NAME"' not in prompt


def test_gate_failure_is_fed_back_and_retried(tmp_path, slot_config, llm_stub):
    bad = {**GOOD, "CLOSING": GOOD["CLOSING"] + " I am the perfect fit!"}
    llm_stub.replies = [json.dumps(bad), json.dumps(GOOD)]
    rc, out = run(tmp_path, slot_config)
    assert rc == 0 and len(llm_stub.requests) == 2
    feedback = llm_stub.requests[1][2]["messages"][-1]["content"]
    assert "exclamation" in feedback and "perfect fit" in feedback


def test_letter_that_keeps_failing_is_never_written(tmp_path, slot_config, llm_stub, capsys):
    llm_stub.replies = [json.dumps({**GOOD, "BODY_PARA_1": "As an AI, I improved latency by 95%."})]
    rc, out = run(tmp_path, slot_config, "--attempts", "2")
    assert rc == 2 and not out.exists() and len(llm_stub.requests) == 2
    err = capsys.readouterr().err
    assert "nothing written" in err and "'AI'" in err and "'95%'" in err


def test_content_file_skips_the_model(tmp_path, slot_config, llm_stub):
    c = tmp_path / "content.json"
    c.write_text(json.dumps(GOOD))
    rc, out = run(tmp_path, slot_config, "--content", str(c))
    assert rc == 0 and out.exists() and llm_stub.requests == []


def test_unknown_template_token_warns_and_leaves_no_braces(tmp_path, slot_config, llm_stub, capsys):
    tpl = tmp_path / "mine.md"
    tpl.write_text(TEMPLATE.read_text() + "\n{{POSTSCRIPT}}\n")
    llm_stub.replies = [json.dumps(GOOD)]
    rc, out = run(tmp_path, slot_config, "--template", str(tpl))
    assert rc == 0
    assert "POSTSCRIPT" in capsys.readouterr().err and "{{" not in out.read_text()


@pytest.mark.parametrize("change, expected", [
    ({"BODY_PARA_1": "", "BODY_PARA_2": "", "BODY_PARA_3": ""}, "length:"),
    ({"BODY_PARA_1": "", "BODY_PARA_2": "", "BODY_PARA_3": "", "OPENING": GOOD["OPENING"] * 3}, "paragraphs:"),
    ({"CLOSING": GOOD["CLOSING"] + " Thanks!"}, "register: exclamation"),
    ({"BODY_PARA_3": "I used a large language model to polish this letter."}, "leak:"),
    ({"BODY_PARA_3": "I admire [Company] and its mission."}, "placeholder:"),
    ({"BODY_PARA_3": "TODO add a sentence about the team."}, "placeholder:"),
    ({"BODY_PARA_3": "I also grew revenue by 45% at a previous employer."}, "grounding: the number '45%'"),
    ({"BODY_PARA_3": "I am passionate about data and would be a perfect fit."}, "register: cliché"),
    ({"BODY_PARA_3": "My salary expectation is flexible."}, "commitment: mentions salary"),
    ({"BODY_PARA_3": "I am open to relocating for this role."}, "commitment: mentions relocation"),
    ({"SIGNATURE": "Best,\nJamie"}, "signature:"),
])
def test_each_gate_fires(change, expected):
    content = {**GOOD, **change}
    letter = bcl.render(TEMPLATE.read_text(), {**content, "FULL_NAME": "Robin Testwell", "CONTACT_LINE": "x",
                                               "DATE": "May 1, 2026", "COMPANY": JD["company"],
                                               "ROLE_TITLE": JD["title"]})
    failures = bcl.gate(content, letter, doc(), JD, bcl.LEAK_TERMS)
    assert any(f.startswith(expected) for f in failures), failures


def test_company_and_role_must_be_named():
    other = {**JD, "company": "Southwind Example Inc"}
    letter = bcl.render(TEMPLATE.read_text(), GOOD)
    assert any(f.startswith("company:") for f in bcl.gate(GOOD, letter, doc(), other, bcl.LEAK_TERMS))
    other = {**JD, "title": "Staff Analytics Engineer (Remote)"}
    assert any(f.startswith("role:") for f in bcl.gate(GOOD, letter, doc(), other, bcl.LEAK_TERMS))


def test_configured_model_names_are_banned(slot_config):
    content = {**GOOD, "BODY_PARA_3": "This was drafted with m-cover_letter for speed."}
    failures = bcl.gate(content, bcl.render(TEMPLATE.read_text(), content), doc(), JD,
                        bcl.banned_terms(slot_config))
    assert any("m-cover_letter" in f for f in failures)
