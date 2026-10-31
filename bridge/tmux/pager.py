"""Conservative local pager evidence; never infer a key from text alone."""
import os
import subprocess
import re
import shlex

SYSTEMCTL_PAGER_COMMANDS = frozenset({
    'status', 'show', 'cat', 'help', 'list-units', 'list-unit-files',
    'list-sockets', 'list-timers', 'list-paths', 'list-automounts',
    'list-dependencies', 'list-jobs', 'list-machines', 'show-environment',
})


def systemctl_pager_command(command):
    """Recognize introspection verbs, not arbitrary words in quoted output.

    Unknown options before a verb fail closed; no shell evaluation is used.
    """
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|()')
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return False
    flags = {'--user', '--system', '--all', '-a', '--full', '-l', '--failed',
             '--reverse', '--plain', '--no-legend', '--no-pager', '--no-ask-password'}
    values = {'-p', '--property', '-t', '--type', '--state', '-H', '--host',
              '-M', '--machine', '-n', '--lines', '--root', '--image'}
    for i, token in enumerate(tokens):
        if (os.path.basename(token) != 'systemctl'
                or (i and tokens[i-1] not in {';', '&&', '||', '|', 'sudo', 'command', 'env'})):
            continue
        i += 1
        while i < len(tokens) and tokens[i].startswith('-'):
            option = tokens[i]
            if option == '--no-pager':
                break
            if option in flags or ('=' in option and option.split('=', 1)[0] in values):
                i += 1
            elif option in values and i + 1 < len(tokens):
                i += 2
            else:
                break
        if i < len(tokens) and tokens[i] in SYSTEMCTL_PAGER_COMMANDS:
            return True
    return False


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
    known = re.search(r'\bgit\s+(?:diff|log|show)\b', command) or systemctl_pager_command(command)
    entered = max(raw.rfind('\x1b[?1049h'), raw.rfind('\x1b[?47h'), raw.rfind('\x1b[?1h'))
    exited = max(raw.rfind('\x1b[?1049l'), raw.rfind('\x1b[?47l'), raw.rfind('\x1b[?1l'))
    return bool(known and entered >= 0 and entered > exited
                and re.search(r'\x1b\[(?:0;)?7m' + END_STATUS, raw[-200:]))
