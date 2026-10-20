#!/usr/bin/env python3
"""Install hermes-job-drop into ~/.hermes. Stdlib only.

    python3 install.py                   # install (never overwrites your files)
    python3 install.py --force           # also overwrite config, profile template, templates
    python3 install.py --doctor          # check the model slots in your config
    python3 install.py --audit-user-data # check your data dir is not tracked by any git repo
"""
import argparse
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
SKILL_NAME = "hermes-job-drop"


def paths():
    home = Path.home()
    return home / ".hermes" / "jobdrop", home / ".hermes" / "skills" / SKILL_NAME


def tilde(p):
    """Show paths as ~/... so output never prints the user's home directory name."""
    try:
        return "~/" + str(Path(p).relative_to(Path.home()))
    except ValueError:
        return str(p)


def copy_user_file(src, dst, force):
    if dst.exists() and not force:
        print(f"  kept     {tilde(dst)}  (exists; --force to overwrite)")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"  wrote    {tilde(dst)}")


def install(force):
    data, skill = paths()
    print("Installing hermes-job-drop")
    for d in (data, data / "templates", data / "applications"):
        d.mkdir(parents=True, exist_ok=True)

    # User-owned files: never overwritten without --force.
    copy_user_file(REPO / "config/config.template.yaml", data / "config.yaml", force)
    copy_user_file(REPO / "templates/master_profile.template.yaml", data / "profile.template.yaml", force)
    copy_user_file(REPO / "templates/resume.html", data / "templates/resume.html", force)
    copy_user_file(REPO / "templates/cover_letter.md", data / "templates/cover_letter.md", force)

    ledger = data / "ledger.db"
    if ledger.exists():
        print(f"  kept     {tilde(ledger)}")
    else:
        sqlite3.connect(ledger).close()  # empty ledger; the schema is created on first write
        print(f"  created  {tilde(ledger)}  (empty)")

    # Kit-owned files: always refreshed so the doctrine and engine stay current.
    skill.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO / SKILL_NAME, skill, dirs_exist_ok=True)
    shutil.copytree(REPO / "scripts", skill / "scripts", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"  updated  {tilde(skill)}  (SKILL.md, references/, scripts/)")
    print_next_steps(data, skill)


def print_next_steps(data, skill):
    s = tilde(skill)
    d = tilde(data)
    print(f"""
Getting to your first application
---------------------------------
1. Point the kit at a folder of your own resumes and documents (PDF, DOCX, HTML, MD, TXT,
   or an existing profile.yaml). It drafts your profile from them:

     python3 {s}/scripts/ingest_profile.py ~/path/to/your-resumes

2. Review {d}/profile.yaml once. Everything in it is what the kit may claim about you;
   anything empty is a question it will ask you, never a guess.

3. Choose a model for each of the six slots in {d}/config.yaml and export the API key env
   vars it names (see examples/example_config.yaml in the repo).

4. Check the setup:

     python3 {s}/scripts/config.py --doctor

5. Make sure Hermes' Discord gateway is running with require_mention on, then post a job
   link in Discord and tag the bot.
""")


def audit_user_data():
    """The user's data dir must not be tracked by any git repo it happens to sit inside."""
    data, _ = paths()
    if not data.exists():
        print(f"{tilde(data)} does not exist yet; run the installer first.")
        return 1
    top = subprocess.run(["git", "-C", str(data), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if top.returncode != 0:
        print(f"OK: {tilde(data)} is not inside any git repository.")
        return 0
    tracked = subprocess.run(["git", "-C", str(data), "ls-files", "."], capture_output=True,
                             text=True).stdout.split()
    ignored = subprocess.run(["git", "-C", str(data), "check-ignore", "-q", "."]).returncode == 0
    if tracked:
        print(f"FAIL: {len(tracked)} file(s) in {tilde(data)} are tracked by git at "
              f"{tilde(top.stdout.strip())}:")
        for f in tracked:
            print(f"  {f}")
        print("Untrack them (git rm --cached) and add the directory to that repo's .gitignore.")
        return 1
    if not ignored:
        print(f"FAIL: {tilde(data)} sits inside the git repo at {tilde(top.stdout.strip())} and "
              f"is not gitignored. Add it to that repo's .gitignore.")
        return 1
    print(f"OK: {tilde(data)} is inside a git repo but gitignored, and nothing in it is tracked.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Install hermes-job-drop into ~/.hermes.")
    ap.add_argument("--force", action="store_true",
                    help="overwrite your existing config, profile template and templates")
    ap.add_argument("--doctor", action="store_true",
                    help="report per-slot model/provider, key presence and endpoint reachability")
    ap.add_argument("--config", help="config file for --doctor (default: ~/.hermes/jobdrop/config.yaml)")
    ap.add_argument("--audit-user-data", action="store_true",
                    help="verify ~/.hermes/jobdrop/ is not tracked by any git repository")
    args = ap.parse_args(argv)
    if args.doctor:
        sys.path.insert(0, str(REPO / "scripts"))
        import config
        return config.doctor(args.config)
    if args.audit_user_data:
        return audit_user_data()
    install(args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
