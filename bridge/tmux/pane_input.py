"""Application input, independent of tmux's history viewer.

Use private, one-shot buffers without bracketed-paste wrapping. Never cancel
copy-mode or use the user's unnamed clipboard buffer.
"""
import uuid

def text_commands(pane, text):
    name = 'stb-input-' + uuid.uuid4().hex
    return [['set-buffer', '-b', name, '--', text],
            ['paste-buffer', '-d', '-r', '-b', name, '-t', pane]]


def key_commands(pane, key):
    controls = {'Enter': '\r', 'Tab': '\t', 'Escape': '\x1b',
                'BSpace': '\x7f', 'Space': ' '}
    if key in controls:
        return text_commands(pane, controls[key])
    if len(key) == 3 and key.startswith('C-') and 'A' <= key[2].upper() <= '_':
        return text_commands(pane, chr(ord(key[2].upper()) & 31))
    # Other keys retain tmux's terminal-aware encoding. The backend refuses
    # them in copy-mode rather than silently operating the history viewer.
    return [['send-keys', '-t', pane, key]]
