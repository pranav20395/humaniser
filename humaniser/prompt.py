"""The exact prompt and sampling settings the humanizer model was trained with.

Source: prompt_format.json in https://huggingface.co/jialinyyzz/humanizer.
The model is a text-completion model, not a chat model: send this string to a
completion endpoint, with no system prompt and no chat turns.
"""

import hashlib

INSTR = (
    "Rewrite the text below so it reads like a person wrote it, not a language model.\n"
    "\n"
    "Reorganize it as you see fit. Vary sentence length on purpose. Cut hedging,\n"
    "throat-clearing, and any sentence that only announces what comes next.\n"
    "Prefer the concrete word over the abstract one. It is fine to sound uneven.\n"
    "\n"
    "Every fact, number, unit, date, name and quotation must survive unchanged."
)
SEP = "\n\n### Rewritten:\n\n"

# First 16 hex chars of sha256(build_prompt("X")), published with the model.
FINGERPRINT = "cc51d66b4c593fbe"

# Sampling the model was evaluated with. top_k, min_p and repeat_penalty must be
# sent explicitly: llama.cpp defaults to top_k 40 / min_p 0.05. Never send stop
# strings; the model ends the rewrite with EOS.
SAMPLING = {
    "temperature": 1.0,
    "top_p": 0.95,
    "top_k": 0,
    "min_p": 0.0,
    "repeat_penalty": 1.0,
}

CONTEXT_TOKENS = 8192


def build_prompt(draft: str) -> str:
    return INSTR + "\n\n" + draft.strip() + SEP


def fingerprint() -> str:
    return hashlib.sha256(build_prompt("X").encode("utf-8")).hexdigest()[:16]


assert fingerprint() == FINGERPRINT, "prompt format drifted from the model's training prompt"
