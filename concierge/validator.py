"""
Answer validator: every number, time, or band word in a reply must appear
somewhere in that turn's tool outputs (including evidence notes), or the
reply is rejected. Catches a model inventing a number the tools never
produced — the offline templates are built directly from tool output, so
they should always pass; this is the real gate for the online (Gemini)
path, where a hallucinated figure would otherwise slip straight through.
"""
import json
import re

# "-" is only a negative sign when NOT immediately preceded by a digit —
# "8.1-14.0" is the range 8.1 to 14.0, not 8.1 and -14.0. Without the
# lookbehind, every "low-high" range in a reply would false-positive as
# an unverifiable negative number.
NUMBER_PATTERN = re.compile(r"(?<!\d)-?\d+(?:\.\d+)?")
BAND_WORDS = ("Low", "Moderate", "High", "Medium")


def validate_reply(text, cards):
    """Returns {"valid": bool, "unverified": [...]}. An empty cards dict
    (e.g. the honest "no live data" refusal, which carries no tool output
    by design) is trivially valid — there's nothing to check numbers
    against because the reply correctly contains none of its own."""
    if not cards:
        return {"valid": True, "unverified": []}

    evidence_blob = json.dumps(cards)
    unverified = []

    for match in NUMBER_PATTERN.finditer(text or ""):
        token = match.group()
        if token not in evidence_blob:
            unverified.append(token)

    for word in BAND_WORDS:
        if re.search(rf"\b{word}\b", text or "") and word not in evidence_blob:
            unverified.append(word)

    # de-duplicate while preserving order
    seen = set()
    unverified = [u for u in unverified if not (u in seen or seen.add(u))]
    return {"valid": len(unverified) == 0, "unverified": unverified}
