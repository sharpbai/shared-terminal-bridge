"""Conservative local pager evidence; never infer a key from text alone."""
import os
import subprocess
import re


END_STATUS = r'(?:lines? \d+(?:-\d+)?/\d+\s+)?\(END\)'


def end_status(line):
    return bool(re.fullmatch(END_STATUS, line.strip()))


def update_cycle(job, chunk):
    """Count alternate-screen lifetimes from new ordered bytes, not snapshots.

    Keep a short suffix for escapes split over output notifications. Repeated
    enter without exit is the same lifetime, even if the pager redraws END.
    """
    pending = job.get('pager_escape_tail', '') + chunk
    for match in re.finditer(r'\x1b\[\?(?:1049|1047|47|1)([hl])', pending):
        active = match[1] == 'h'
        if active and not job.get('pager_screen_active'):
            job['pager_cycle'] = job.get('pager_cycle', 0) + 1
        job['pager_screen_active'] = active
    partial = re.search(r'\x1b(?:\[(?:\?(?:[0-9]*))?)?$', pending)
    job['pager_escape_tail'] = partial[0] if partial else ''
    return job.get('pager_cycle', 0)


def at_pager_end(content, tty, raw='', command=''):
    if not content or not end_status(content[-1]):
        return False
    try:
        result = subprocess.run(['ps', '-t', tty.removeprefix('/dev/'),
            '-o', 'pgid=,tpgid=,comm='], capture_output=True, text=True,
            timeout=1, check=True)
    except (OSError, subprocess.SubprocessError):
        return False
    foreground = []
    for line in result.stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0] == fields[1]:
            foreground.append(os.path.basename(fields[2]))
    local = bool(set(foreground) & {'less', 'more'}) and not (
        set(foreground) & {'vim', 'vi', 'nvim', 'ssh', 'mosh', 'mosh-client'})
    if local:
        return True
    # No remote probes or wrappers. Narrow remote heuristic: a pager-producing
    # command, SSH transport, active alternate screen and inverse-video END.
    # Explicit user-selected pagers/editors and shell substitutions fail closed.
    if (not set(foreground) & {'ssh', 'mosh-client'}
            or re.search(r'PAGER\s*=|`|\$\(|\b(?:vim|nvim|vi)\b', command)):
        return False
    known = re.search(r'\b(?:git\s+(?:diff|log|show)|systemctl\s+(?:status|cat|list-units))\b', command)
    entered = max(raw.rfind('\x1b[?1049h'), raw.rfind('\x1b[?47h'), raw.rfind('\x1b[?1h'))
    exited = max(raw.rfind('\x1b[?1049l'), raw.rfind('\x1b[?47l'), raw.rfind('\x1b[?1l'))
    return bool(known and entered >= 0 and entered > exited
                and re.search(r'\x1b\[(?:0;)?7m' + END_STATUS, raw[-200:]))
