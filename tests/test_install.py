import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(home, *args):
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(["bash", str(ROOT / "install.sh"), *args], env=env, capture_output=True, text=True)


def test_install_creates_layout_and_never_overwrites_without_force(tmp_path):
    r = run(tmp_path)
    assert r.returncode == 0, r.stderr
    data = tmp_path / ".hermes/jobdrop"
    skill = tmp_path / ".hermes/skills/hermes-job-drop"
    for p in ["config.yaml", "profile.template.yaml", "templates/resume.html",
              "templates/cover_letter.md", "ledger.db"]:
        assert (data / p).exists(), p
    assert (skill / "SKILL.md").exists() and (skill / "references/ats-form-shapes.md").exists()
    assert (skill / "scripts/config.py").exists()
    # next steps: profile-folder ingestion is step 1; output shows ~/ paths, not the real home
    assert "1. Point the kit at a folder of your own resumes" in r.stdout
    assert "tag the bot" in r.stdout and str(tmp_path) not in r.stdout

    cfg = data / "config.yaml"
    cfg.write_text("# my edits\n")
    r = run(tmp_path)
    assert r.returncode == 0 and cfg.read_text() == "# my edits\n"
    assert "kept     ~/.hermes/jobdrop/config.yaml" in r.stdout

    r = run(tmp_path, "--force")
    assert r.returncode == 0 and "version: 1" in cfg.read_text()


def test_audit_user_data_outside_git(tmp_path):
    run(tmp_path)
    r = run(tmp_path, "--audit-user-data")
    assert r.returncode == 0 and "OK:" in r.stdout


def test_audit_user_data_flags_tracked_files(tmp_path):
    run(tmp_path)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", ".hermes/jobdrop/config.yaml"], check=True)
    r = run(tmp_path, "--audit-user-data")
    assert r.returncode == 1 and "config.yaml" in r.stdout
