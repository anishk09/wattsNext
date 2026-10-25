"""
Privacy filter: blocks premise IDs, equipment/location codes, precise
coordinates, and facility-location keywords from reaching the AI or the
browser. Applied to every chat reply right before it leaves the server —
a defensive gate, since the data files themselves are already built
without these fields (see scripts/build_data.py), but this is the backstop
that makes "never" an enforced property instead of just an intention.
"""
import re

PATTERNS = {
    # AEP equipment/location codes (e.g. 37800045000064) and premise
    # numbers (e.g. 247057282) are both long digit runs — nothing this
    # app legitimately emits is an 8+ digit integer.
    "long_id_number": re.compile(r"\b\d{8,}\b"),
    # Location codes sometimes carry an embedded letter block (e.g.
    # 37800343D00129).
    "equipment_location_code": re.compile(r"\b\d{5,}[A-Z]\d{4,}\b"),
    # Lat/long with GIS-export precision (source data carries ~10 decimal
    # digits, e.g. -80.2125770318). 7+ digits keeps this well clear of our
    # own rate figures, which are rounded to 6 decimal places at most.
    "coordinate": re.compile(r"-?\d{1,3}\.\d{7,}"),
    # Internal substation/circuit labels (e.g. STATION29, CIR6) used
    # throughout cases.json and the risk-model join — never meant to reach
    # a customer. Backstop: the real fix is templates that never embed
    # them (see engine.py RISK_FALLBACK_REASONS); this catches any other
    # path that might.
    "internal_grid_label": re.compile(r"\bSTATION\d+\b|\bCIR\d+\b", re.IGNORECASE),
}

FACILITY_KEYWORDS = re.compile(
    r"\b(hospital|fire station|ambulance service|medical center|dialysis center)\b",
    re.IGNORECASE,
)

REDACTED = "[redacted]"


def scrub(text):
    """Returns (clean_text, violations). Each violation names which
    pattern matched — logged to the audit trail even though it should
    always be empty in practice, so the control is demonstrably live."""
    if not text:
        return text, []
    violations = []
    clean = text
    for kind, pattern in PATTERNS.items():
        matches = pattern.findall(clean)
        if matches:
            violations.append({"type": kind, "count": len(matches)})
            clean = pattern.sub(REDACTED, clean)
    if FACILITY_KEYWORDS.search(clean):
        violations.append({"type": "facility_keyword"})
        clean = FACILITY_KEYWORDS.sub(REDACTED, clean)
    return clean, violations
