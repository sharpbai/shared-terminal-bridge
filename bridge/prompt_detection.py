"""Conservative prompt-family matching without changing the target shell."""

import re

def returned_prompt(baseline, content):
    """Recognize a prompt after output without a newline, only at a shell
    readline-enable boundary. A textual suffix alone is not completion proof.
    This remains a terminal heuristic, not a trusted process-exit protocol.
    """
    from bridge.context_policy import AIContextPolicy
    lines = AIContextPolicy.normalize(content)
    tail = next((line.strip() for line in reversed(lines) if line.strip()), '')
    if same_prompt_family(baseline, tail):
        return tail
    boundary = '\x1b[?2004h'
    if boundary in content:
        suffix = content.rsplit(boundary, 1)[1]
        lines = [line.strip() for line in AIContextPolicy.normalize(suffix) if line.strip()]
        if len(lines) == 1 and same_prompt_family(baseline, lines[0]):
            return lines[0]
        # First task after a history reset may inherit a contaminated screen
        # baseline. Recover only a full user@host:path prompt at the explicit
        # readline boundary, already present as that baseline's exact suffix.
        if (len(lines) == 1 and baseline.strip().endswith(lines[0])
                and re.fullmatch(r'[\w.-]+@[\w.-]+:[^\r\n]+[#$%]', lines[0])):
            return lines[0]
    return None


def same_prompt_family(baseline, candidate):
    baseline, candidate = baseline.strip(), candidate.strip()
    # Ctrl+C may be visibly echoed directly before the returned prompt. That
    # screen becomes the next job's baseline too; do not bake ^C into its identity.
    while baseline.startswith('^C'):
        baseline = baseline[2:].lstrip()
    while candidate.startswith('^C'):
        candidate = candidate[2:].lstrip()
    if baseline and candidate == baseline:
        return True
    # Preserve a recognizable machine/user prefix and terminal prompt marker;
    # only the cwd/branch part may vary. A bare '$' or arbitrary output ending
    # with '#' is not sufficient evidence.
    pattern = r"^([^\s:]+:).+?\s*([$#%])$"
    before = re.fullmatch(pattern, baseline)
    after = re.fullmatch(pattern, candidate)
    return bool(before and after and before.groups() == after.groups())
