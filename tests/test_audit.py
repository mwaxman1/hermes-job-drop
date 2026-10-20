import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "scripts" / "audit_no_personal_data.py"
sys.path.insert(0, str(ROOT / "scripts"))
import audit_no_personal_data as audit  # noqa: E402

# Planted values are assembled at runtime so this tracked file stays clean under its own audit.
J = "".join
REAL_EMAIL = J(["jane.q.doe", "@", "gmail", ".com"])
REAL_PHONE = J(["(415) 86", "7-5309"])
REAL_STREET = J(["1234 Elm", " Street, Apt 5"])
REAL_LINKEDIN = J(["https://www.linkedin.com/in/", "jane", "qdoe"])
REAL_HOME = J(["/ho", "me/", "janedoe", "/resumes/cv.md"])


def run_audit(repo):
    return subprocess.run([sys.executable, str(AUDIT), "--root", str(repo)], capture_output=True, text=True)


def make_repo(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for rel, content in files.items():
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content if isinstance(content, bytes) else content.encode())
    subprocess.run(["git", "-C", str(repo), "add", "-A", "-f"], check=True)
    return repo


def test_clean_real_repo_passes():
    r = run_audit(ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK:" in r.stdout


def test_planted_personal_data_fails(tmp_path):
    repo = make_repo(tmp_path, {
        "README.md": "# fine\nContact: someone@example.com, 555-0142\n",
        "notes.md": "\n".join([
            "email me at " + REAL_EMAIL,
            "call " + REAL_PHONE,
            "I live at " + REAL_STREET,
            "profile " + REAL_LINKEDIN,
            "source " + REAL_HOME,
        ]) + "\n",
        ".env": "API_KEY=x\n",
        "resume.pdf": b"%PDF-1.7\n\0binary",
        "ledger.db": b"SQLite format 3\0",
    })
    r = run_audit(repo)
    assert r.returncode == 1, r.stdout
    out = r.stdout
    for expected in [
        "notes.md:1: [email]",
        "notes.md:2: [phone]",
        "notes.md:3: [street-address]",
        "notes.md:4: [linkedin-url]",
        "notes.md:5: [home-path]",
        ".env:0: [banned-file:.env]",
        "resume.pdf:0: [banned-file:.pdf]",
        "ledger.db:0: [banned-file:.db]",
    ]:
        assert expected in out, f"missing {expected!r} in:\n{out}"
    assert REAL_EMAIL in out  # the offending line is printed
    assert "README.md" not in out  # example.com and the fictional 555-01xx range are allowed


def test_each_violation_alone_fails(tmp_path):
    # Every rule must fail the build on its own, not just in aggregate.
    cases = {
        "a.txt": REAL_EMAIL, "b.txt": REAL_PHONE, "c.txt": REAL_STREET,
        ".env.local": "X=1", "cv.pdf": b"%PDF-1.4",
    }
    for i, (rel, content) in enumerate(cases.items()):
        repo = make_repo(tmp_path / str(i), {rel: content})
        assert run_audit(repo).returncode == 1, rel


def test_untracked_files_are_ignored(tmp_path):
    repo = make_repo(tmp_path, {"ok.md": "hello\n"})
    (repo / ".env").write_text("SECRET=1\n")
    (repo / "notes.md").write_text(REAL_EMAIL + "\n")
    r = run_audit(repo)
    assert r.returncode == 0, r.stdout


def test_env_example_and_placeholders_allowed(tmp_path):
    repo = make_repo(tmp_path, {
        ".env.example": "ANTHROPIC_API_KEY=\n",
        "templates/resume.html": "<p>{{EMAIL}} {{PHONE}} {{CITY}}, {{STATE}}</p>\n",
        "docs.md": "paths look like /home/<name>/ or /home/runner/work; write you@<domain>\n",
    })
    r = run_audit(repo)
    assert r.returncode == 0, r.stdout


def test_local_denylist(tmp_path):
    term = J(["Acme", "Widgets"])
    repo = make_repo(tmp_path, {"cover.md": f"I loved my years at {term}.\n"})
    assert run_audit(repo).returncode == 0
    (repo / audit.DENYLIST_NAME).write_text("# my private terms\n" + term.lower() + "\n")
    r = run_audit(repo)
    assert r.returncode == 1 and "cover.md:1: [denylist]" in r.stdout
    # and the denylist itself must never be tracked
    subprocess.run(["git", "-C", str(repo), "add", "-f", audit.DENYLIST_NAME], check=True)
    assert "[banned-file:local-denylist]" in run_audit(repo).stdout


@pytest.mark.parametrize("line", ["2024-01-15", "2018 - 2021", "v3.14.4", "127.0.0.1", "{{PHONE}}"])
def test_no_false_positive_phone(line):
    assert "phone" not in list(audit.line_hits(line, []))
