"""Bound session inspection: all its panes and only its unfinished jobs."""

from stb_cli.client import bridge_call, tmux


def session_info(args, session):
    result = tmux(args.tmux_socket, "list-panes", "-s", "-t", session["session_id"],
                  "-F", "#{pane_id}\t#{window_id}\t#{pane_index}\t#{pane_current_command}\t#{pane_current_path}",
                  capture=True)
    panes = []
    for line in result.stdout.splitlines():
        pane, window, index, command, path = line.split("\t", 4)
        panes.append(dict(pane=pane, window=window, index=int(index),
                          current_command=command, cwd=path))
    info = dict(session, panes=panes, current_jobs=[], jobs_available=True)
    try:
        jobs = bridge_call(args.bridge_socket, "terminal_job_list").get("jobs", [])
    except RuntimeError as error:
        # Missing Bridge is not evidence of an idle terminal. Never start/restart
        # it here: info remains an inspection command.
        info.update(jobs_available=False, jobs_error=str(error))
        return info
    pane_ids = {pane["pane"] for pane in panes}
    fields = ("job_id", "pane", "state", "execution_phase", "elapsed_ms",
              "resource_class", "attention_reason")
    for job in jobs:
        if job.get("pane") in pane_ids and job.get("execution_phase") == "EXECUTING":
            info["current_jobs"].append({key: job[key] for key in fields if key in job})
    return info
