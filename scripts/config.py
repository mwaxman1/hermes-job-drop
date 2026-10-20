#!/usr/bin/env python3
"""Load and validate the six model slots from ~/.hermes/jobdrop/config.yaml.

There is no default model. Every slot must name its own model + provider (or a `command:`
that starts an external driver). A missing slot is a hard error naming the slot and the file.

    python3 scripts/config.py [--config PATH]            # validate and print the slots
    python3 scripts/config.py [--config PATH] --doctor   # + key presence and reachability

Secret values are never printed: key resolution reports presence as a boolean only.
"""
import argparse
import os
import re
import shlex
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

SLOTS = ("vision", "tooling", "browser", "python", "resume", "cover_letter")
SLOT_KEYS = {"model", "provider", "base_url", "api_key_env", "temperature", "command"}
DEFAULT_CONFIG = Path("~/.hermes/jobdrop/config.yaml")

# Ambient key + endpoint per known provider, used when the slot does not set its own.
# ponytail: small static table; add a provider here when someone needs it.
PROVIDERS = {
    "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/models"),
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1/models"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/models"),
    "google": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/models"),
    "gemini": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/models"),
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1/models"),
    "mistral": ("MISTRAL_API_KEY", "https://api.mistral.ai/v1/models"),
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com/models"),
    "xai": ("XAI_API_KEY", "https://api.x.ai/v1/models"),
    "ollama": (None, "http://localhost:11434/api/tags"),  # local, no key
}
ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ConfigError(Exception):
    """The config file is unusable. The message says what to fix and where."""


class MissingSlotError(ConfigError):
    def __init__(self, slots, path):
        self.slots = slots
        super().__init__(
            f"missing model slot(s): {', '.join(slots)} in {path}. "
            f"Add a `models.<slot>:` entry with `model:` and `provider:` for each "
            f"(see config/config.template.yaml). There is no default model."
        )


@dataclass(frozen=True)
class Slot:
    name: str
    model: str = None
    provider: str = None
    base_url: str = None
    api_key_env: str = None
    temperature: float = None
    command: str = None

    @property
    def key_env(self):
        """The env var the key comes from: the slot's own, else the provider's ambient one."""
        return self.api_key_env or PROVIDERS.get(self.provider, (None, None))[0]

    def key_status(self):
        """'present' | 'unresolved' | 'not-required'. Never returns the value."""
        if self.command:
            return "not-required"
        env = self.key_env
        if env is None:
            # Known keyless provider (local), or a custom endpoint with no key configured.
            return "not-required" if self.provider == "ollama" or self.base_url else "unresolved"
        return "present" if os.environ.get(env, "").strip() else "unresolved"

    @property
    def endpoint(self):
        return self.base_url or PROVIDERS.get(self.provider, (None, None))[1]

    def describe(self):
        if self.command:
            return f"command: {self.command}"
        return f"{self.provider} / {self.model}"


def _load_yaml(path):
    try:
        import yaml
    except ImportError:
        raise ConfigError("PyYAML is required to read the config: python3 -m pip install --user pyyaml")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path} is not valid YAML: {e}")


def load_config(path=None):
    """Return {slot_name: Slot} for all six slots, or raise ConfigError / MissingSlotError."""
    path = Path(path or DEFAULT_CONFIG).expanduser()
    if not path.is_file():
        raise ConfigError(f"config not found: {path}. Run install.sh, then edit that file.")
    raw = _load_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping with `version:` and `models:`")
    if raw.get("version") != 1:
        raise ConfigError(f"{path}: `version: 1` is required (got {raw.get('version')!r})")
    models = raw.get("models")
    if not isinstance(models, dict):
        raise ConfigError(f"{path}: `models:` must be a mapping of the six slots: {', '.join(SLOTS)}")

    problems = []
    unknown = sorted(set(models) - set(SLOTS))
    if unknown:
        problems.append(
            f"unknown slot(s): {', '.join(unknown)} (valid slots: {', '.join(SLOTS)})"
        )
    missing = [s for s in SLOTS if not models.get(s)]
    slots = {}
    for name in SLOTS:
        entry = models.get(name)
        if not entry:
            continue
        if not isinstance(entry, dict):
            problems.append(f"slot {name}: must be a mapping")
            continue
        extra = sorted(set(entry) - SLOT_KEYS)
        if extra:
            hint = " (put the key in an env var and name it in `api_key_env:`)" if any(
                "key" in k for k in extra) else ""
            problems.append(f"slot {name}: unknown key(s) {', '.join(extra)}{hint}")
        command = entry.get("command")
        blank = [f"`{f}`" for f in ("model", "provider")
                 if not (isinstance(entry.get(f), str) and entry[f].strip())]
        if blank and not command:
            problems.append(f"slot {name}: {' and '.join(blank)} required (no default model)")
        if command is not None and not (isinstance(command, str) and command.strip()):
            problems.append(f"slot {name}: `command` must be a non-empty string")
        base_url = entry.get("base_url")
        if base_url and not str(base_url).startswith(("http://", "https://")):
            problems.append(f"slot {name}: `base_url` must start with http:// or https://")
        key_env = entry.get("api_key_env")
        if key_env and not ENV_NAME_RE.fullmatch(str(key_env)):
            problems.append(
                f"slot {name}: `api_key_env` must be an env var NAME, not a key value"
            )
        temp = entry.get("temperature")
        if temp is not None and (isinstance(temp, bool) or not isinstance(temp, (int, float)) or not 0 <= temp <= 2):
            problems.append(f"slot {name}: `temperature` must be a number between 0 and 2")
        slots[name] = Slot(
            name=name,
            model=entry.get("model"),
            provider=(entry.get("provider") or "").strip().lower() or None,
            base_url=base_url or None,
            api_key_env=key_env or None,
            temperature=temp,
            command=command or None,
        )
    if missing:
        err = MissingSlotError(missing, path)
        if problems:
            err.args = (err.args[0] + " Also: " + "; ".join(problems),)
        raise err
    if problems:
        raise ConfigError(f"{path}: " + "; ".join(problems))
    return slots


def check_reachable(slot, timeout=5):
    """(ok, short_reason). One minimal request; never returns a response body."""
    if slot.command:
        exe = shlex.split(slot.command)[0]
        return (True, f"{exe} on PATH") if shutil.which(os.path.expanduser(exe)) else (False, f"{exe} not found")
    url = slot.endpoint
    if not url:
        return False, f"no known endpoint for provider '{slot.provider}'; set base_url"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=timeout) as r:
            return True, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return True, f"HTTP {e.code}"  # the server answered; auth is the key check's job
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        return False, type(reason).__name__ if not isinstance(reason, str) else reason[:60]


def doctor(path=None, out=sys.stdout):
    """Print a per-slot health report. Returns 0 if every slot is usable, else 1."""
    path = Path(path or DEFAULT_CONFIG).expanduser()
    try:
        slots = load_config(path)
    except ConfigError as e:
        print(f"config: FAIL  {e}", file=out)
        return 1
    print(f"config: ok  {path}", file=out)
    bad = 0
    for name in SLOTS:
        s = slots[name]
        key = s.key_status()
        ok, why = check_reachable(s)
        key_ok = key != "unresolved"
        bad += (not key_ok) + (not ok)
        key_txt = f"key_present={key == 'present'}" + (
            f" ({s.key_env} unresolved)" if key == "unresolved" and s.key_env
            else " (unresolved: set api_key_env)" if key == "unresolved"
            else " (not required)" if key == "not-required" else f" ({s.key_env})")
        print(f"  {name:<13} {s.describe():<45} {key_txt:<40} endpoint={'ok' if ok else 'fail'} ({why})",
              file=out)
    print("doctor: all slots usable" if not bad else f"doctor: {bad} problem(s) above", file=out)
    return 0 if not bad else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate the hermes-job-drop model-slot config.")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG), help="config file (default: %(default)s)")
    ap.add_argument("--doctor", action="store_true", help="also check key presence and endpoint reachability")
    args = ap.parse_args(argv)
    if args.doctor:
        return doctor(args.config)
    try:
        slots = load_config(args.config)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for name in SLOTS:
        print(f"{name:<13} {slots[name].describe()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
