import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ledger  # noqa: E402

URL = "https://jobs.lever.co/example-org/1f2e3d4c-aaaa-4bbb-8ccc-ddddeeee0001"


@pytest.fixture
def conn(tmp_path):
    return ledger.connect(tmp_path / "ledger.db")


def test_url_key_normalizes_the_same_posting():
    same = [
        URL,
        URL + "/apply?utm_source=discord&lever-source=x",
        "<" + URL.replace("https://jobs.lever.co", "HTTPS://WWW.Jobs.Lever.CO") + "/>",
        URL + "#top",
    ]
    assert len({ledger.url_key(u) for u in same}) == 1, [ledger.url_key(u) for u in same]
    assert ledger.url_key("https://careers.example.com/open-roles?gh_jid=40123") == "greenhouse:40123"
    assert ledger.url_key("https://job-boards.greenhouse.io/exampleorg/jobs/40123") == "greenhouse:40123"
    assert ledger.url_key("https://jobs.ashbyhq.com/example/abc/application") == \
        ledger.url_key("https://jobs.ashbyhq.com/example/abc")
    assert ledger.url_key("https://example.com/jobs?id=1") != ledger.url_key("https://example.com/jobs?id=2")


def test_round_trip_dedupe_submit_report(conn):
    first = ledger.add_drop(conn, URL, note="remote only")
    assert first["action"] == "new" and first["state"] == "received"
    again = ledger.add_drop(conn, URL + "?utm_campaign=x")
    assert again == {**again, "id": first["id"], "action": "duplicate"}
    assert conn.execute("SELECT COUNT(*) FROM drops").fetchone()[0] == 1  # never a second application

    ledger.update_drop(conn, first["id"], company="Example Org", title='Data Engineer, "Platform"')
    for s in ("resolving", "documents_ready", "filling"):
        ledger.set_state(conn, first["id"], s)
    with pytest.raises(ledger.LedgerError, match="confirmation"):
        ledger.record_submission(conn, first["id"], job_url=URL)
    row = ledger.record_submission(conn, first["id"], job_url=URL + "/apply", ats="lever",
                                   resume_path="/tmp/x/resume.pdf", cover_letter_path=None,
                                   confirmation_url=URL + "/thanks", confirmation_text="Application submitted!",
                                   method="chrome-plugin")
    assert row["state"] == "submitted" and row["confirmation_text"] == "Application submitted!"
    assert [e["event"] for e in row["events"]] == [
        "received", "redrop", "resolving", "documents_ready", "filling", "submitted"]
    text = ledger.report(ledger.readback(conn, first["id"]))
    assert text.splitlines()[0] == 'SUBMITTED — Data Engineer, "Platform" at Example Org'
    assert "Resume: resume.pdf · Cover letter: none (no field)" in text
    assert 'Confirmation: "Application submitted!"' in text
    # a re-drop after submission is a no-op that reports the existing state
    assert ledger.add_drop(conn, URL)["state"] == "submitted"


def test_states_are_constrained(conn):
    d = ledger.add_drop(conn, URL)
    with pytest.raises(ledger.LedgerError, match="unknown state"):
        ledger.set_state(conn, d["id"], "done")
    with pytest.raises(ledger.LedgerError, match="use `submit`"):
        ledger.set_state(conn, d["id"], "submitted")
    with pytest.raises(sqlite3.IntegrityError):  # and the database itself refuses
        conn.execute("UPDATE drops SET state = 'done' WHERE id = ?", (d["id"],))


def test_parked_drop_resumes_and_reports_the_question(conn):
    d = ledger.add_drop(conn, URL)
    ledger.update_drop(conn, d["id"], company="Example Org", title="Analyst")
    ledger.set_state(conn, d["id"], "parked",
                     'label="Are you legally authorized to work in Canada?" required=yes type=radio '
                     'options=["Yes","No"] form=open')
    text = ledger.report(ledger.readback(conn, d["id"]))
    assert text.startswith("PARKED — Analyst at Example Org")
    assert '"Are you legally authorized to work in Canada?" (required)' in text
    assert "Options: Yes | No" in text and "still open" in text
    r = ledger.add_drop(conn, URL, note="answer: Yes")
    assert r["action"] == "resumed" and r["id"] == d["id"]


def test_already_applied_list(conn):
    by_url = ledger.add_drop(conn, URL, already_applied=[URL + "/apply"])
    assert by_url["state"] == "duplicate" and by_url["action"] == "already_applied"
    d = ledger.add_drop(conn, "https://jobs.ashbyhq.com/example/xyz", already_applied=["Example Org — Analyst"])
    assert d["state"] == "received"
    row = ledger.update_drop(conn, d["id"], "Example Org", "Analyst", ["Example Org — Analyst"])
    assert row["state"] == "duplicate"
    assert ledger.report(ledger.readback(conn, d["id"])).startswith("DUPLICATE — Analyst at Example Org")


def test_cli(tmp_path):
    db = tmp_path / "l.db"

    def cli(*a):
        r = subprocess.run([sys.executable, str(ROOT / "scripts/ledger.py"), "--db", str(db), *a],
                           capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr
    rc, out, _ = cli("add", URL, "--note", "referral")
    assert rc == 0 and json.loads(out)["action"] == "new"
    rc, out, _ = cli("add", URL)
    assert json.loads(out)["action"] == "duplicate"
    rc, _, err = cli("state", "1", "nonsense")
    assert rc != 0
    rc, _, err = cli("submit", "1", "--job-url", URL)
    assert rc == 1 and "not a submission" in err
    rc, out, _ = cli("state", "1", "failed", "--detail", "posting closed")
    rc, out, _ = cli("report", "1")
    assert out.startswith("FAILED — ") and "posting closed" in out
