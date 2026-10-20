import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config  # noqa: E402
import llm  # noqa: E402
from conftest import TEST_KEY  # noqa: E402


def test_resolve_slot_from_config_and_key_from_env(slot_config, monkeypatch, llm_stub):
    # model names in the environment are never consulted: only the slot's own entry counts
    for var in ("ANTHROPIC_MODEL", "OPENAI_MODEL", "MODEL", "LLM_MODEL"):
        monkeypatch.setenv(var, "env-model-must-not-be-used")
    r = llm.resolve("cover_letter", slot_config)
    assert (r.model, r.provider, r.key, r.key_env) == ("m-cover_letter", "custom", TEST_KEY, "JD_TEST_KEY")
    assert r.chat_url == llm_stub.url + "/v1/chat/completions"
    assert TEST_KEY not in repr(r)
    llm_stub.replies = ['```json\n{"ok": true}\n```']
    assert llm.parse_json(llm.chat("vision", [{"role": "user", "content": "hi"}], config_path=slot_config)) == {"ok": True}
    assert llm_stub.models == ["m-vision"]


def test_errors_never_leak_the_key(tmp_path, monkeypatch):
    monkeypatch.delenv("JD_MISSING_KEY", raising=False)
    models = {s: {"model": f"m-{s}", "provider": "openai", "api_key_env": "JD_MISSING_KEY"} for s in config.SLOTS}
    models["browser"] = {"command": "my-agent"}
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({"version": 1, "models": models}))
    with pytest.raises(llm.LLMError, match="JD_MISSING_KEY"):
        llm.resolve("resume", p)
    with pytest.raises(llm.LLMError, match="command"):
        llm.resolve("browser", p)
    with pytest.raises(llm.LLMError, match="unknown slot"):
        llm.resolve("embeddings", p)
    monkeypatch.setenv("JD_MISSING_KEY", TEST_KEY)
    r = subprocess.run([sys.executable, str(ROOT / "scripts/llm.py"), "resume", "--show", "--config", str(p)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "model=m-resume" in r.stdout and "key_present=True" in r.stdout
    assert TEST_KEY not in r.stdout + r.stderr


def test_chat_url_shapes():
    assert llm.chat_url("https://ollama.com") == "https://ollama.com/v1/chat/completions"
    assert llm.chat_url("http://localhost:11434") == "http://localhost:11434/v1/chat/completions"
    assert llm.chat_url("https://openrouter.ai/api/v1/") == "https://openrouter.ai/api/v1/chat/completions"
    assert llm.chat_url("https://x.example.com/v1beta/openai") == "https://x.example.com/v1beta/openai/chat/completions"
    assert llm.chat_url("https://gw.example.com/chat/completions") == "https://gw.example.com/chat/completions"
