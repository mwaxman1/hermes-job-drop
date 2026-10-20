#!/usr/bin/env python3
"""Resolve a model slot and talk to it over an OpenAI-compatible chat endpoint.

Every model call in the kit goes through here, and the model always comes from the slot in
~/.hermes/jobdrop/config.yaml — never from code, an env var, or another slot.

    python3 scripts/llm.py SLOT --show              # resolved model/provider/endpoint, key presence
    python3 scripts/llm.py SLOT "prompt text"       # one chat turn, prints the reply

The HTTP layer is plain `POST {base}/chat/completions` with a bearer key, so it works with
OpenAI, OpenRouter, Ollama (local or cloud), Groq, Mistral, Anthropic's and Gemini's
OpenAI-compatible endpoints, and any local server that speaks the same shape.
Key values are never printed or put in an error message.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

# Default OpenAI-compatible base per provider, used only when the slot has no base_url.
CHAT_BASE = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "xai": "https://api.x.ai/v1",
    "ollama": "http://localhost:11434/v1",
}


class LLMError(Exception):
    """A slot could not be resolved or the endpoint refused. Never contains a key value."""


@dataclass(frozen=True)
class Resolved:
    slot: str
    model: str
    provider: str
    base_url: str
    key: str = field(default=None, repr=False)  # repr=False: never shows up in logs or tracebacks
    key_env: str = None
    temperature: float = None

    @property
    def chat_url(self):
        return chat_url(self.base_url)


def chat_url(base):
    """`…/chat/completions` for a base URL, whether or not it already carries /v1."""
    base = base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    path = base.split("://", 1)[-1].partition("/")[2]
    return base + ("/chat/completions" if re.search(r"(^|/)v\d", path) else "/v1/chat/completions")


def resolve(slot_name, config_path=None):
    """slot name → Resolved(model, provider, base_url, key) from config.yaml, or LLMError."""
    if slot_name not in config.SLOTS:
        raise LLMError(f"unknown slot {slot_name!r} (valid: {', '.join(config.SLOTS)})")
    try:
        slot = config.load_config(config_path)[slot_name]
    except config.ConfigError as e:
        raise LLMError(str(e))
    if slot.command:
        raise LLMError(f"slot {slot_name} is a `command:` slot (an external driver); it has no chat model")
    base = slot.base_url or CHAT_BASE.get(slot.provider)
    if not base:
        raise LLMError(f"slot {slot_name}: provider {slot.provider!r} has no known endpoint; "
                       f"set `base_url:` for it in config.yaml")
    env = slot.key_env
    key = os.environ.get(env, "").strip() if env else ""
    if not key and slot.key_status() == "unresolved":
        raise LLMError(f"slot {slot_name}: no API key — set the env var "
                       f"{env or '(none configured; set api_key_env)'} where Hermes runs")
    return Resolved(slot_name, slot.model, slot.provider, base, key or None, env, slot.temperature)


def _post(url, payload, key, timeout):
    """The HTTP layer: one JSON POST, returns the parsed JSON body."""
    headers = {"Content-Type": "application/json", "User-Agent": "hermes-job-drop"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        if key:
            body = body.replace(key, "***")
        raise LLMError(f"{url} answered HTTP {e.code}: {body}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise LLMError(f"{url} unreachable: {getattr(e, 'reason', e)}")


def chat(slot_name, messages, *, config_path=None, timeout=180, temperature=None):
    """Send `messages` to the slot's model and return the reply text."""
    r = resolve(slot_name, config_path)
    payload = {"model": r.model, "messages": messages, "stream": False}
    temp = temperature if temperature is not None else r.temperature
    if temp is not None:
        payload["temperature"] = temp
    data = _post(r.chat_url, payload, r.key, timeout)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"slot {slot_name}: unexpected response shape from {r.chat_url}")
    if isinstance(content, list):  # some servers return content parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def parse_json(reply):
    """The first JSON object in a model reply (tolerates code fences and chatter), or LLMError."""
    reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.S)
    start = reply.find("{")
    while start != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(reply[start:])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
        start = reply.find("{", start + 1)
    raise LLMError("model reply contained no JSON object")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Resolve a model slot / send it one prompt.")
    ap.add_argument("slot", choices=config.SLOTS)
    ap.add_argument("prompt", nargs="?", help="prompt text (omit with --show)")
    ap.add_argument("--show", action="store_true", help="print the resolved slot; never the key")
    ap.add_argument("--config", help="config file (default: ~/.hermes/jobdrop/config.yaml)")
    args = ap.parse_args(argv)
    try:
        if args.show or not args.prompt:
            r = resolve(args.slot, args.config)
            print(f"{r.slot}: model={r.model} provider={r.provider} endpoint={r.chat_url} "
                  f"key_present={bool(r.key)}" + (f" ({r.key_env})" if r.key_env else ""))
            return 0
        print(chat(args.slot, [{"role": "user", "content": args.prompt}], config_path=args.config))
        return 0
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
