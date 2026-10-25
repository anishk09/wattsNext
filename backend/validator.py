import re

NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?")

def validate(text, whitelist):
    allowed = {round(float(v), 1) for v in whitelist}
    found = [float(x) for x in NUMBER.findall(text)]
    rejected = [x for x in found if round(x, 1) not in allowed]
    return {"passed": not rejected, "numbers": found, "rejected": rejected}
