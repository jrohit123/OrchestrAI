"""The flow builder prototype with the real AI behind it.

Serves docs/design (the prototype pages) on 127.0.0.1 only, and answers POST /api/ai by asking OpenAI with the key in
openai.local.key next to this file (never committed). The key stays on this computer: the page never sees it.

    python docs/ux/tools/flow_ai_server.py            then open http://127.0.0.1:8766/flow-builder-v3.html
"""

import json
import os
import sys
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = os.path.normpath(os.path.join(HERE, "..", "..", "design"))
PORT = int(os.environ.get("FLOW_AI_PORT", "8766"))
MODELS = ("gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini")  # gpt-4.1 first: gpt-4o-mini (what the app uses today) invented questions in testing
_KEY_FILE = os.path.join(HERE, "openai.local.key")
KEY = open(_KEY_FILE, encoding="utf-8").read().strip() if os.path.exists(_KEY_FILE) else ""
os.environ["NO_PROXY"] = ",".join(filter(None, [os.environ.get("NO_PROXY"), "127.0.0.1", "localhost", "api.openai.com"]))


def ask_openai(model: str, messages: list[dict]) -> dict:
    body = json.dumps(
        {"model": model, "messages": messages, "temperature": 0.2, "response_format": {"type": "json_object"}}
    ).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # straight to OpenAI, no proxy
    with opener.open(req, timeout=90) as r:
        data = json.loads(r.read())
    return {
        "content": json.loads(data["choices"][0]["message"]["content"]),
        "tokens": data.get("usage", {}).get("total_tokens"),
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=PAGES, **k)

    def log_message(self, fmt, *args):
        if "/api/" in str(args[0] if args else ""):
            sys.stderr.write("%s\n" % (fmt % args))

    def _send(self, code: int, obj: dict) -> None:
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/ai/status":
            return self._send(200, {"ready": bool(KEY), "models": MODELS})
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/ai":
            return self._send(404, {"error": "not found"})
        if not KEY:
            return self._send(503, {"error": "No key: put it in docs/ux/tools/openai.local.key"})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            model = req.get("model") if req.get("model") in MODELS else MODELS[0]
            messages = [m for m in req.get("messages", []) if m.get("role") in ("system", "user", "assistant")][-24:]
            out = ask_openai(model, messages)
            sys.stderr.write(f"AI {model}: {out['tokens']} tokens\n")
            return self._send(200, {"model": model, **out})
        except urllib.error.HTTPError as e:
            return self._send(502, {"error": f"OpenAI said {e.code}: {e.read()[:300].decode(errors='replace')}"})
        except Exception as e:  # the page shows it; nothing else to protect here
            return self._send(500, {"error": repr(e)[:300]})


if __name__ == "__main__":
    print(f"Flow builder with the real AI: http://127.0.0.1:{PORT}/flow-builder-v3.html  (key {'found' if KEY else 'MISSING'})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
