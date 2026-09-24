"""Human-readable and JSON formatting for STB CLI results."""

import json

def print_sessions(sessions, as_json=False):
    if as_json:
        print(json.dumps(sessions, ensure_ascii=False, indent=2))
        return
    if not sessions:
        print("当前没有托管的 tmux 会话。")
        print("可使用：stb create <名称> --cwd <目录>")
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
    print("\n进入会话：stb enter <名称>")

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
