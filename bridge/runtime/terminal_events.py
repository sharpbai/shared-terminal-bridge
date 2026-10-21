"""Apply pane-local ordered events to execution state, never wall-clock sorting."""

import threading

from bridge.common import BridgeError, now
from bridge.context_policy import AIContextPolicy
from bridge.execution.lifecycle import EXECUTING, FINISHED, execution_phase
from bridge.prompt_detection import returned_prompt
from bridge.tmux.control_stream import ControlStream
from bridge.tmux.pager import update_cycle, end_status


class TerminalEventService:
    def __init__(self, bridge):
        self.bridge = bridge
        self.streams = {}
        self.positions = {}
        self.broken_panes = set()
        self.start_lock = threading.Lock()

    def ensure_terminal_stream(self, pane):
        with self.start_lock:
            return self._ensure_stream(pane)

    def _ensure_stream(self, pane):
        if pane in self.broken_panes:
            raise BridgeError('TERMINAL_EVENT_STREAM_UNAVAILABLE', pane=pane)
        # Minimal fake/third-party backends retain their explicit test path.
        if not hasattr(self.bridge.tmux, 'run'):
            return None
        stream = self.streams.get(pane)
        if stream is not None:
            if stream.closed.is_set():
                raise BridgeError('TERMINAL_EVENT_STREAM_UNAVAILABLE', pane=pane)
            return stream
        stream = ControlStream(self.bridge.tmux, pane, self.handle_terminal_event)
        self.streams[pane] = stream
        return stream

    def close_terminal_streams(self):
        for stream in list(self.streams.values()):
            stream.close()
        self.streams.clear()

    def handle_terminal_event(self, event):
        pane, epoch, seq = event['pane'], event['stream_epoch'], event['stream_seq']
        with self.bridge.lock:
            position = self.positions.get(pane)
            if position and position[0] == epoch and seq <= position[1]:
                return
            if (not position and seq != 1) or (position and (position[0] != epoch or seq != position[1] + 1)):
                self.broken_panes.add(pane)
                self.bridge.record('TERMINAL_EVENT_GAP', pane=pane)
                for candidate in self.bridge.jobs.values():
                    if candidate['pane'] == pane and execution_phase(candidate) == EXECUTING:
                        candidate.update(event_stream_lost=True, state='NEEDS_ATTENTION',
                                         attention_reason='terminal_event_gap')
                        self.bridge._signal_job_waits(candidate['job_id'], candidate['state'])
                self.bridge.persist_state()
                return
            self.positions[pane] = (epoch, seq)
            if event['type'] == 'stream_lost':
                self.broken_panes.add(pane)
                for candidate in self.bridge.jobs.values():
                    if (candidate['pane'] == pane and execution_phase(candidate) == EXECUTING
                            and candidate.get('event_stream_pending')):
                        candidate.update(event_stream_lost=True, state='NEEDS_ATTENTION',
                                         attention_reason='terminal_event_stream_lost')
                        self.bridge._signal_job_waits(candidate['job_id'], candidate['state'])
                self.bridge.persist_state()
            scope = event.get('scope') or {}
            job = self.bridge.jobs.get(scope.get('job_id'))
            if (not job or job['pane'] != pane
                    or job['generation'] != scope.get('generation')):
                return
            if event['type'] == 'command_started':
                job['stream_epoch'] = epoch
                job['event_stream_pending'] = False
            if job.get('stream_epoch') != epoch:
                return
            job['last_stream_seq'] = seq
            if event['type'] == 'agent_interrupt_requested':
                if execution_phase(job) == EXECUTING:
                    job.update(agent_interrupt_requested_at=now(),
                               agent_interrupt_id=event['interrupt_id'],
                               state='RUNNING', attention_reason=None)
                    self.bridge.persist_state()
                return
            if event['type'] == 'stream_lost':
                job['event_stream_lost'] = True
                if execution_phase(job) == EXECUTING:
                    job.update(state='NEEDS_ATTENTION', attention_reason='terminal_event_stream_lost')
                    self.bridge.persist_state()
                    self.bridge._signal_job_waits(job['job_id'], job['state'])
                    self.bridge.record('JOB_STATE', pane=pane, job_id=job['job_id'],
                                       state=job['state'], stream_epoch=epoch, stream_seq=seq)
                    threading.Thread(target=self.bridge._notify_job, args=(job,), daemon=True).start()
                self.bridge.record('TERMINAL_EVENT_STREAM_LOST', pane=pane, job_id=job['job_id'])
                return
            if event['type'] == 'terminal_output' and execution_phase(job) == EXECUTING:
                content = event['content']
                chunk = event.get('output_chunk')
                if chunk is None:
                    previous = job.get('last_content', '')
                    chunk = content[len(previous):] if content.startswith(previous) else content
                cycle = update_cycle(job, chunk)
                already_exited = job.get('pager_exit_cycle') == cycle
                job['last_content'] = content
                job['last_activity_at'] = now()
                job['output_excerpt'] = AIContextPolicy.job_output(
                    job['baseline_content'], content, job['command'])
                prompt = returned_prompt(job.get('baseline_prompt', ''), content)
                if prompt:
                    job['returned_prompt'] = prompt
                    self.bridge.pane_prompts[pane] = dict(
                        prompt=prompt, pane_command=job.get('baseline_pane_command'))
                    job.update(state=('INTERRUPTED_BY_AGENT' if job.get('agent_interrupt_requested_at')
                                      else 'COMPLETED'), execution_phase=FINISHED,
                               completion_confidence='ordered_prompt_returned', completed_at=now())
                    self.bridge.persist_state()
                    self.bridge._signal_job_waits(job['job_id'], job['state'])
                    self.bridge.record('JOB_STATE', pane=pane, job_id=job['job_id'],
                                       state=job['state'], stream_epoch=epoch, stream_seq=seq)
                    threading.Thread(target=self.bridge._notify_job, args=(job,), daemon=True).start()
                else:
                    lines = [line.strip() for line in AIContextPolicy.normalize(content) if line.strip()]
                    if (not already_exited
                            and hasattr(self.bridge.tmux, 'pager_at_end')
                            and self.bridge.tmux.pager_at_end(pane, lines, content, job['command'])):
                        self.bridge.require_lease(pane, job['generation'])
                        job['pager_exit_requested'] = True
                        job['pager_exit_cycle'] = cycle
                        job['pager_exit_count'] = job.get('pager_exit_count', 0) + 1
                        self.bridge.persist_state()
                        self.bridge.tmux.send_text(pane, 'q')
                        self.bridge.record('AGENT_PAGER_EXIT', pane=pane,
                                           job_id=job['job_id'], source='agent', pager_cycle=cycle)
                        return
                    if lines and end_status(lines[-1]) and not already_exited:
                        job.update(state='NEEDS_ATTENTION', attention_reason='pager_unconfirmed')
                        self.bridge.persist_state()
                        self.bridge._signal_job_waits(job['job_id'], job['state'])
                        return
                    prompt = self.bridge._interaction_prompt(job['output_excerpt']['content'])
                    if prompt:
                        job.update(state='NEEDS_ATTENTION', attention_reason=prompt)
                        self.bridge._signal_job_waits(job['job_id'], job['state'])
            elif event['type'] == 'human_interrupt':
                # Only the state produced by earlier events can authorize this
                # transition. Never read the post-C-c terminal here.
                self.bridge.handle_human_event(dict(event, ordered=True))
