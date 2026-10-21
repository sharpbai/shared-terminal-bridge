"""One tmux control connection: ordered output, submit fences and human keys.

Never merge independently timestamped sockets. tmux queues %message behind
previous output on this connection. Each reconnect starts a new stream epoch.
No output is stored here beyond the current bounded terminal tail.
"""

import codecs
import re
import shlex
import subprocess
import threading
import uuid

from bridge.common import BridgeError
from bridge.runtime.admission import receive
from bridge.tmux.pane_input import text_commands, key_commands


def decode_output(value):
    return re.sub(rb"\\([0-7]{3})", lambda m: bytes([int(m[1], 8)]), value)


class ControlStream:
    def __init__(self, backend, pane, callback):
        self.backend, self.pane, self.callback = backend, pane, callback
        self.epoch = uuid.uuid4().hex
        self.sequence = 0
        self.scope = None
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self.tail = ''
        self.ready = threading.Event()
        self.closed = threading.Event()
        self.write_lock = threading.Lock()
        session = backend.run('display-message', '-p', '-t', pane, '#{session_id}').stdout.strip()
        self.process = subprocess.Popen(
            ['tmux', '-L', backend.socket_name, '-C', 'attach-session',
             '-f', 'ignore-size', '-t', session],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        if not self.ready.wait(5) or self.closed.is_set():
            self.close()
            raise BridgeError('TERMINAL_EVENT_STREAM_UNAVAILABLE', pane=pane)
        clients = backend.run('list-clients', '-F', '#{client_pid}\t#{client_name}').stdout
        self.client = next((line.split('\t', 1)[1] for line in clients.splitlines()
                            if line.startswith(str(self.process.pid) + '\t')), None)
        if not self.client:
            self.close()
            raise BridgeError('TERMINAL_EVENT_STREAM_UNAVAILABLE', pane=pane)
        backend.run('set-option', '-p', '-t', pane, '@stb_event_client', self.client)

    def _emit(self, kind, **values):
        self.sequence += 1
        self.callback(dict(type=kind, pane=self.pane, stream_epoch=self.epoch,
                           stream_seq=self.sequence, scope=self.scope,
                           _received=receive(), **values))

    def _line(self, line):
        # Command responses are reliable even when transient client messages
        # are suppressed. Both forms remain readable for old recorded streams.
        if line.startswith((b'STB_START ', b'STB_AGENT_INTERRUPT ')):
            line = b'%message ' + line
        if line.startswith(b'%session-changed '):
            self.ready.set()
        elif line.startswith(b'%output '):
            parts = line.rstrip(b'\n').split(b' ', 2)
            if len(parts) != 3 or parts[1].decode() != self.pane:
                return
            chunk = self.decoder.decode(decode_output(parts[2]))
            self.tail = (self.tail + chunk)[-32768:]
            self._emit('terminal_output', content=self.tail, output_chunk=chunk)
        elif line.startswith(b'%message STB_START '):
            parts = line.decode().strip().split()
            if len(parts) != 5 or parts[2] != self.pane:
                return
            self.scope = dict(job_id=parts[3], generation=int(parts[4]))
            self.tail = ''
            self.decoder.reset()
            self._emit('command_started')
        elif line.startswith(b'%message STB_INTERRUPT '):
            parts = line.decode().strip().split()
            if len(parts) >= 3 and parts[2] == self.pane:
                self._emit('human_interrupt', client=parts[3] if len(parts) > 3 else '')
        elif line.startswith(b'%message STB_AGENT_INTERRUPT '):
            parts = line.decode().strip().split()
            if (len(parts) == 6 and parts[2] == self.pane
                    and self.scope == dict(job_id=parts[3], generation=int(parts[4]))):
                self._emit('agent_interrupt_requested', interrupt_id=parts[5])
        elif line.startswith((b'%pause ', b'%exit', b'%error ')):
            raise RuntimeError('control stream lost continuity')

    def _read(self):
        reason = 'eof'
        try:
            for line in self.process.stdout:
                self._line(line)
        except Exception as error:
            reason = type(error).__name__
        finally:
            self.closed.set()
            self.ready.set()
            self._emit('stream_lost', reason=reason)
            if self.process.poll() is None:
                self.process.terminate()

    def submit(self, job_id, generation, text):
        if self.closed.is_set():
            raise BridgeError('TERMINAL_EVENT_STREAM_UNAVAILABLE', pane=self.pane)
        commands = [
            ['display-message', '-p', '-l',
             f'STB_START {self.pane} {job_id} {generation}'],
        ] + text_commands(self.pane, text + '\r')
        payload = ' ; '.join(' '.join(shlex.quote(x) for x in cmd) for cmd in commands) + '\n'
        with self.write_lock:
            try:
                self.process.stdin.write(payload.encode())
                self.process.stdin.flush()
            except (OSError, ValueError) as error:
                raise BridgeError('TERMINAL_EVENT_STREAM_UNAVAILABLE', pane=self.pane) from error

    def close(self):
        client = getattr(self, 'client', None)
        if client:
            current = self.backend.run('show-options', '-pqv', '-t', self.pane,
                                       '@stb_event_client', check=False).stdout.strip()
            if current == client:
                self.backend.run('set-option', '-pu', '-t', self.pane,
                                 '@stb_event_client', check=False)
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        if threading.current_thread() is not self.reader:
            self.reader.join(timeout=2)
        for file in (self.process.stdin, self.process.stdout):
            file.close()

    def interrupt(self, job_id, generation, interrupt_id):
        """Order request provenance before the key and its resulting output."""
        if self.closed.is_set():
            raise BridgeError('TERMINAL_EVENT_STREAM_UNAVAILABLE', pane=self.pane)
        commands = [
            ['display-message', '-p', '-l',
             f'STB_AGENT_INTERRUPT {self.pane} {job_id} {generation} {interrupt_id}'],
        ] + key_commands(self.pane, 'C-c')
        payload = ' ; '.join(' '.join(shlex.quote(x) for x in cmd) for cmd in commands) + '\n'
        with self.write_lock:
            try:
                self.process.stdin.write(payload.encode())
                self.process.stdin.flush()
            except (OSError, ValueError) as error:
                raise BridgeError('TERMINAL_EVENT_STREAM_UNAVAILABLE', pane=self.pane) from error
