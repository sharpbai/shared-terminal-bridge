"""Conservative prompt-family matching without changing the target shell."""

import re


def same_prompt_family(baseline, candidate):
    baseline, candidate = baseline.strip(), candidate.strip()
    if baseline and candidate == baseline:
        return True
    # Preserve a recognizable machine/user prefix and terminal prompt marker;
    # only the cwd/branch part may vary. A bare '$' or arbitrary output ending
    # with '#' is not sufficient evidence.
    pattern = r"^([^\s:]+:).+?\s*([$#%])$"
    before = re.fullmatch(pattern, baseline)
    after = re.fullmatch(pattern, candidate)
    return bool(before and after and before.groups() == after.groups())
