"""Unix socket listeners and Bridge request serving lifecycle."""

import json
import os
import pathlib
import socket
import threading

from bridge.common import BridgeError

class SocketServerService:
    def __init__(self, bridge):
        self.bridge = bridge

    @staticmethod
    def prepare_socket(path: pathlib.Path):
        if path.exists():
            path.unlink()

    def event_loop(self):
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.bridge.event_listener = listener
        listener.settimeout(0.2)
        listener.bind(str(self.bridge.event_socket))
        os.chmod(self.bridge.event_socket, 0o600)
        while not self.bridge.stop_event.is_set():
            try:
                payload = listener.recv(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                event = json.loads(payload)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.bridge.record("EVENT_REJECT", reason="INVALID_JSON")
                continue
            self.bridge.handle_human_event(event)

    def handle_connection(self, connection):
        with connection:
            reader = connection.makefile("r", encoding="utf-8")
            writer = connection.makefile("w", encoding="utf-8")
            line = reader.readline()
            try:
                request = json.loads(line)
                result = self.bridge.dispatch(
                    request.get("method", ""),
                    request.get("params") or {},
                )
                response = {"ok": True, "result": result}
            except BridgeError as error:
                response = error.response()
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                response = {
                    "ok": False,
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": str(error),
                    },
                }
            writer.write(json.dumps(response, ensure_ascii=False) + "\n")
            writer.flush()

    def serve(self):
        self.bridge.prepare_socket(self.bridge.control_socket)
        self.bridge.prepare_socket(self.bridge.event_socket)
        event_thread = threading.Thread(target=self.bridge.event_loop, daemon=True)
        event_thread.start()
        job_thread = threading.Thread(target=self.bridge.job_monitor_loop, daemon=True)
        job_thread.start()

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.bridge.control_listener = listener
        listener.settimeout(0.2)
        listener.bind(str(self.bridge.control_socket))
        os.chmod(self.bridge.control_socket, 0o600)
        listener.listen()
        self.bridge.record(
            "SERVER_START",
            control_socket=str(self.bridge.control_socket),
            event_socket=str(self.bridge.event_socket),
        )

        while not self.bridge.stop_event.is_set():
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self.bridge.handle_connection,
                args=(connection,),
                daemon=True,
            ).start()

        self.bridge.stop_event.set()
        listener.close()
        if self.bridge.event_listener:
            self.bridge.event_listener.close()
        event_thread.join(timeout=1)
        job_thread.join(timeout=1)
        for path in (self.bridge.control_socket, self.bridge.event_socket):
            if path.exists():
                path.unlink()
        self.bridge.release_instance_lock()

    def stop(self):
        self.bridge.stop_event.set()
        if self.bridge.control_listener:
            self.bridge.control_listener.close()
