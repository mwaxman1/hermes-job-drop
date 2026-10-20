import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config  # noqa: E402

TEST_KEY = "sk-test-DO-NOT-PRINT-0xfeedface"


class Stub:
    """A local OpenAI-compatible /v1/chat/completions server. Records every request."""

    def __init__(self):
        self.requests = []   # (model, authorization header, payload)
        self.replies = []    # reply texts, served in order; the last one repeats
        stub = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.requests.append((body.get("model"), self.headers.get("Authorization"), body))
                text = stub.replies.pop(0) if len(stub.replies) > 1 else (stub.replies or ["{}"])[0]
                out = json.dumps({"choices": [{"message": {"role": "assistant", "content": text}}]}).encode()
                self.send_response(200 if self.path.endswith("/chat/completions") else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def models(self):
        return [m for m, _, _ in self.requests]


@pytest.fixture
def llm_stub():
    s = Stub()
    yield s
    s.server.shutdown()


@pytest.fixture
def slot_config(tmp_path, llm_stub, monkeypatch):
    """A config whose six slots each name a different model, all served by the stub."""
    monkeypatch.setenv("JD_TEST_KEY", TEST_KEY)
    models = {s: {"model": f"m-{s}", "provider": "custom", "base_url": llm_stub.url + "/v1",
                  "api_key_env": "JD_TEST_KEY"} for s in config.SLOTS}
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"version": 1, "models": models}))
    return p
