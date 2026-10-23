"""Pull the JSON object out of a model reply (models like to add prose or code fences)."""

from __future__ import annotations

import json
from typing import Any

MAX_ATTEMPTS = 20


def first_json_object(text: str) -> dict[str, Any]:
    """The first `{...}` in `text` that parses as a JSON object; ValueError when there is none."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    tries = 0
    while start != -1 and tries < MAX_ATTEMPTS:
        tries += 1
        try:
            value, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    raise ValueError("Jawaban tidak berisi objek JSON.")
