import io
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config  # noqa: E402

SECRET = "sk-test-DO-NOT-PRINT-0xdeadbeef"


def full_models():
    return {s: {"model": f"m-{s}", "provider": "openai", "api_key_env": "JD_TEST_KEY"} for s in config.SLOTS}


def write(tmp_path, models, version=1):
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"version": version, "models": models}))
    return p


def test_valid_config_loads(tmp_path):
    slots = config.load_config(write(tmp_path, full_models()))
    assert set(slots) == set(config.SLOTS)
    assert slots["cover_letter"].model == "m-cover_letter"
    assert slots["vision"].provider == "openai"


def test_missing_slot_is_named_error(tmp_path):
    models = full_models()
    del models["cover_letter"]
    p = write(tmp_path, models)
    with pytest.raises(config.MissingSlotError) as e:
        config.load_config(p)
    assert e.value.slots == ["cover_letter"]
    assert "cover_letter" in str(e.value) and str(p) in str(e.value)


def test_slot_without_model_is_error_not_default(tmp_path):
    models = full_models()
    models["resume"] = {"provider": "openai"}
    with pytest.raises(config.ConfigError, match="resume: `model` required"):
        config.load_config(write(tmp_path, models))


def test_unknown_slot_is_reported(tmp_path):
    models = full_models()
    models["embeddings"] = {"model": "x", "provider": "openai"}
    with pytest.raises(config.ConfigError, match="unknown slot.*embeddings"):
        config.load_config(write(tmp_path, models))


def test_raw_api_key_in_config_is_rejected(tmp_path):
    models = full_models()
    models["vision"]["api_key"] = SECRET
    with pytest.raises(config.ConfigError) as e:
        config.load_config(write(tmp_path, models))
    assert "api_key_env" in str(e.value) and SECRET not in str(e.value)


def test_command_overrides_model(tmp_path, monkeypatch):
    models = full_models()
    models["browser"] = {"command": "my-agent --headed"}  # no model/provider needed
    slots = config.load_config(write(tmp_path, models))
    b = slots["browser"]
    assert b.command == "my-agent --headed"
    assert b.describe() == "command: my-agent --headed"
    # and with a model present too, command still wins
    models["browser"] = {"command": "my-agent", "model": "ignored", "provider": "openai"}
    assert config.load_config(write(tmp_path, models))["browser"].describe() == "command: my-agent"
    # the rest of the config still applies
    assert slots["vision"].describe() == "openai / m-vision"


def test_missing_key_reports_unresolved_without_value(tmp_path, monkeypatch):
    monkeypatch.delenv("JD_TEST_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(config, "check_reachable", lambda s, timeout=5: (True, "stub"))
    p = write(tmp_path, full_models())
    assert config.load_config(p)["vision"].key_status() == "unresolved"
    out = io.StringIO()
    assert config.doctor(p, out=out) == 1
    assert "key_present=False (JD_TEST_KEY unresolved)" in out.getvalue()


def test_doctor_reports_presence_never_value(tmp_path, monkeypatch):
    monkeypatch.setenv("JD_TEST_KEY", SECRET)
    monkeypatch.setattr(config, "check_reachable", lambda s, timeout=5: (False, "stub"))
    out = io.StringIO()
    rc = config.doctor(write(tmp_path, full_models()), out=out)
    text = out.getvalue()
    assert SECRET not in text
    assert text.count("key_present=True") == 6
    assert text.count("endpoint=fail") == 6 and rc == 1


def test_shipped_yaml_files(tmp_path):
    # The template documents every slot but names no model: loading it must fail loudly.
    tpl = (ROOT / "config/config.template.yaml").read_text()
    for slot in config.SLOTS:
        assert f"  {slot}:" in tpl and f"# {slot} —" in tpl
    with pytest.raises(config.ConfigError, match="`model` and `provider` required"):
        config.load_config(ROOT / "config/config.template.yaml")
    assert set(config.load_config(ROOT / "examples/example_config.yaml")) == set(config.SLOTS)

    # Profile template and example persona carry every required section.
    required = {"contact", "summary", "experience", "education", "skills", "certifications", "links"}
    for rel in ("templates/master_profile.template.yaml", "examples/example_profile.yaml"):
        doc = yaml.safe_load((ROOT / rel).read_text())
        assert required <= set(doc), rel
        assert {"first_name", "last_name", "email", "phone", "city", "state"} <= set(doc["contact"]), rel
    example = yaml.safe_load((ROOT / "examples/example_profile.yaml").read_text())
    assert example["contact"]["email"].endswith("@example.com")
    assert example["experience"] and all(r["bullets"] for r in example["experience"])
