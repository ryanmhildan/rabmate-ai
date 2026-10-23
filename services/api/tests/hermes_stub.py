"""A stand-in for Hermes Agent's API server — FOR TESTING ONLY, not an AI.

It speaks the few endpoints RABmate's adapter uses (`/health`, `/v1/toolsets`,
`/v1/chat/completions`) and answers deterministically, so the real HTTP adapter, background jobs
and the review UI can be exercised end to end on a machine without Hermes or a model:

- extraction prompts: rows of a pipe/tab table become items, numbers copied verbatim;
- draft prompts: one line per sentence of the description, quantities copied when written.

Run (binds 127.0.0.1 only):
    .venv/Scripts/python.exe -m tests.hermes_stub --port 8642 --key <same as HERMES_API_KEY>
Add `--unsafe` to report an enabled `terminal` toolset (the adapter must then refuse).
"""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

NUMBER = re.compile(r"\d[\d.,]*")


def _extract(content: str) -> dict[str, Any]:
    items = []
    for line in content.splitlines():
        match = re.match(r"\[(\d+)\]\s*(.*)", line)
        if not match:
            continue
        cells = [c.strip() for c in re.split(r"\s*[|\t]\s*", match.group(2)) if c.strip()]
        if len(cells) > 3 and cells[0].isdigit():
            cells = cells[1:]  # leading row number ("No")
        numeric = [c for c in cells if NUMBER.fullmatch(c)]
        words = [c for c in cells if not NUMBER.fullmatch(c) and c != "-"]
        if len(words) < 2 or not numeric:
            continue
        name, unit = words[0], words[-1]
        items.append(
            {
                "name": name,
                "quantity_text": numeric[0],
                "unit": unit,
                "unit_price_text": numeric[1] if len(numeric) > 1 else None,
                "total_text": numeric[2] if len(numeric) > 2 else None,
                "source_line": int(match.group(1)),
                "unknown_fields": [] if len(numeric) > 1 else ["harga satuan"],
            }
        )
    return {"items": items, "notes": ["Jawaban stub pengujian, bukan model AI."]}


def _draft(content: str) -> dict[str, Any]:
    payload = json.loads(content)
    sentences = [s.strip() for s in re.split(r"[.;\n]", payload["deskripsi"]) if len(s.strip()) > 3]
    items = []
    for sentence in sentences[:10]:
        number = NUMBER.search(sentence)
        items.append(
            {
                "name": sentence[:80],
                "item_type": "service",
                "quantity_text": number.group(0) if number else None,
                "unit": "ls",
            }
        )
    return {
        "items": items,
        "assumptions": ["Jawaban stub pengujian, bukan model AI."],
        "questions": ["Volume pekerjaan yang tidak tertulis perlu diisi."],
    }


class Handler(BaseHTTPRequestHandler):
    key = ""
    unsafe = False

    def _send(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {self.key}"

    def do_GET(self) -> None:
        if self.path in ("/health", "/v1/health"):
            self._send(200, {"status": "ok"})
        elif self.path == "/v1/toolsets":
            if not self._authorized():
                self._send(401, {"error": "unauthorized"})
                return
            toolsets = [
                {"name": "terminal", "enabled": self.unsafe, "configured": True, "tools": []}
            ]
            self._send(200, {"toolsets": toolsets})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions" or not self._authorized():
            self._send(404 if self._authorized() else 401, {"error": "no"})
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        system = body["messages"][0]["content"]
        user = body["messages"][1]["content"]
        answer = _extract(user) if "ekstraksi" in system else _draft(user)
        self._send(
            200,
            {
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "model": f"{body.get('model', 'rabmate')} (stub pengujian)",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": json.dumps(answer)}}
                ],
            },
        )

    def log_message(self, format: str, *args: Any) -> None:  # keep test output quiet
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8642)
    parser.add_argument("--key", required=True)
    parser.add_argument("--unsafe", action="store_true")
    args = parser.parse_args()
    Handler.key = args.key
    Handler.unsafe = args.unsafe
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Hermes STUB (pengujian, bukan AI) di http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
