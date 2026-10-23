"""Optional: let a language model phrase a chat answer (`BLE_CHAT_MODEL`, e.g. a Claude model id).

The model only rewrites what the tools returned. It sees the tool lines with their [E1] markers and
must keep a marker on every sentence that states a fact; the chat verifier then drops any line that
cites evidence the tools did not return, and any line with a number but no citation. If the model
is not configured or fails, the deterministic answer stands.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable

PROMPT = """You rewrite answers for a construction estimator reviewing bids. Below are facts from tools,
each ending in evidence markers like [E3]. Answer the question in the language of the question, briefly,
using only these facts. Keep the markers: every sentence that states a fact ends with the marker(s) of
the facts it uses. Do not add facts, numbers or names that are not in the lines.

Question: {question}

Facts:
{facts}"""


def _claude(model: str) -> Callable[[str], str]:
    import anthropic  # optional dependency: pip install .[llm]

    client = anthropic.Anthropic()

    def call(prompt: str) -> str:
        r = client.messages.create(model=model, max_tokens=800, messages=[{"role": "user", "content": prompt}])
        return "".join(str(getattr(b, "text", "")) for b in r.content if b.type == "text")

    return call


def phrase(question: str, facts: str, complete: Callable[[str], str] | None = None) -> str | None:
    model = os.environ.get("BLE_CHAT_MODEL")
    if complete is None:
        if not model:
            return None
        try:
            complete = _claude(model)
        except Exception:
            return None
    try:
        out = complete(PROMPT.format(question=question, facts=facts)).strip()
    except Exception:
        return None
    # a line that states a number must cite where it came from
    kept = [ln for ln in out.splitlines() if ln.strip() and (re.search(r"\[E\d+\]", ln) or not re.search(r"\d", ln))]
    return "\n".join(kept) or None
