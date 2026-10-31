"""Human-readable and JSON formatting for STB CLI results."""

import json

def print_sessions(sessions, as_json=False):
    if as_json:
        print(json.dumps(sessions, ensure_ascii=False, indent=2))
        return
    if not sessions:
        print("当前没有托管的 tmux 会话。")
        return
    print(f"托管的 tmux 会话：{len(sessions)} 个")
    for session in sessions:
        print(f"\n  {session['name']}")
        print(f"    主面板：{session['pane']}")
        print(f"    已连接客户端：{session['attached']}")
        print(f"    窗口数：{session['windows']}")
        print(f"    历史行数：{session['history_limit']}")
        print(f"    鼠标：{'已开启' if session['mouse'] else '已关闭'}")
        print(f"    创建时间：{session['created_at']}")

def print_session_info(session):
    print(f"会话名称：{session['name']}")
    print(f"会话 ID：{session['session_id']}")
    print(f"托管 ID：{session['managed_id']}")
    print(f"主面板：{session['pane']}")
    print(f"窗口数：{session['windows']}")
    print(f"已连接客户端：{session['attached']}")
    print(f"历史行数：{session['history_limit']}")
    print(f"鼠标支持：{'已开启' if session['mouse'] else '已关闭'}")
    print(f"创建时间：{session['created_at']}")
    print("\n面板（包含所有窗口）：")
    for pane in session.get("panes", []):
        print(f"  {pane['pane']}  窗口={pane['window']}  序号={pane['index']}  "
              f"程序={pane['current_command']}  目录={pane['cwd']}")
    print("\n当前任务：")
    if not session.get("jobs_available", False):
        print(f"  无法查询：{session.get('jobs_error', 'Bridge 不可用')}；不能据此判断终端空闲。")
    elif not session.get("current_jobs"):
        print("  Bridge 未跟踪此会话的未结束任务（不代表没有人工启动的命令）。")
    else:
        for job in session["current_jobs"]:
            print(f"  {job['job_id']}  {job['state']}  pane={job['pane']}  "
                  f"已运行 {job.get('elapsed_ms', 0) // 1000}s")
        print("  详情：stb job <任务ID>；继续等待：stb wait <任务ID>")
