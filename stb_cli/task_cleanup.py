"""Explicit local maintenance; never sends input or kills a pane process."""
import json
import os
import shutil
import tempfile
from datetime import datetime

from stb_cli.config import DEFAULT_STATE_FILE, DEFAULT_BRIDGE_SOCKET
from stb_cli.daemon import stop_bridge_daemon, start_bridge_daemon


def clear_unfinished(state, pane=None):
    selected = {key for key, job in state.get('jobs', {}).items()
                if job.get('execution_phase') == 'EXECUTING'
                and (pane is None or job.get('pane') == pane)}
    for entry in state.get('command_requests', {}).values():
        if (entry.get('state') == 'RETURNED'
                and (entry.get('result') or {}).get('job_id') in selected):
            entry.pop('result', None)
            entry.update(state='REJECTED', error=dict(code='TERMINAL_JOB_STATE_CLEARED',
                details=dict(reason='manual task cleanup; never replay the old request')))
    for key in selected:
        del state['jobs'][key]
    return sorted(selected)


def cleanup(args):
    if args.tmux_socket != 'default' or args.bridge_socket != DEFAULT_BRIDGE_SOCKET:
        raise RuntimeError('清理命令目前仅支持本机默认 Bridge，拒绝修改其他实例。')
    if not DEFAULT_STATE_FILE.exists():
        print('没有可清理的任务状态。')
        return 0
    state = json.loads(DEFAULT_STATE_FILE.read_text())
    if state.get('tmux_socket') != 'default':
        raise RuntimeError('状态文件的 tmux socket 不匹配。')
    selected = clear_unfinished(state, args.pane)
    if not selected:
        print('没有匹配的未结束任务。')
        return 0
    print('待清理任务：' + ', '.join(selected))
    print('仅删除 Bridge 跟踪状态，不停止实际命令。重启将撤销所有当前租约。')
    if not args.yes:
        print('预览模式：确认终端可用后，加 --yes 执行清理。')
        return 0
    stop_bridge_daemon()
    try:
        # Reload after shutdown: the daemon may have saved newer state.
        state = json.loads(DEFAULT_STATE_FILE.read_text())
        backup = DEFAULT_STATE_FILE.with_name(DEFAULT_STATE_FILE.stem +
            '.before-task-cleanup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
        shutil.copy2(DEFAULT_STATE_FILE, backup)
        os.chmod(backup, 0o600)
        selected = clear_unfinished(state, args.pane)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=DEFAULT_STATE_FILE.parent,
                                             prefix='.stb-cleanup-', delete=False) as output:
                temporary = output.name
                json.dump(state, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, DEFAULT_STATE_FILE)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
    finally:
        start_bridge_daemon(args.tmux_socket, args.bridge_socket)
    print(f'已清理 {len(selected)} 条任务，Bridge 已重启。备份：{backup}')
    return 0
