"""Concurrent JSON-RPC dispatch over MCP stdio."""

import json
import sys
import threading

from mcp_server.transport import MCPError

class StdioService:
    def __init__(self, server):
        self.server = server

    def dispatch(self, request):
        if request.get("jsonrpc") != "2.0" or not isinstance(
            request.get("method"), str
        ):
            raise MCPError(-32600, "Invalid Request")
        method = request["method"]
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise MCPError(-32602, "params must be an object")
        if method == "server/discover":
            self.server.validate_modern_request(request)
            return self.server.discover()
        if method == "initialize":
            return self.server.initialize(params)
        if method == "notifications/cancelled":
            target = params.get("requestId", params.get("request_id"))
            self.server.cancel_request(target)
            return None
        if method == "notifications/initialized":
            return None
        modern = self.server.validate_modern_request(request)
        if not modern and not self.server.legacy_initialized:
            raise MCPError(-32002, "Server is not initialized")
        if method == "ping":
            return {}
        if method == "tools/list":
            return self.server.list_tools(modern)
        if method == "tools/call":
            return self.server.call_tool(params, modern, request_id=request.get("id"))
        raise MCPError(-32601, "Method not found", {"method": method})

    def handle(self, request):
        request_id = request.get("id") if isinstance(request, dict) else None
        try:
            result = self.server.dispatch(request)
            if request_id is None or result is None:
                return None
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except MCPError as error:
            if request_id is None:
                return None
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": error.code, "message": error.message},
            }
            if error.data is not None:
                payload["error"]["data"] = error.data
            return payload

    def run_stdio(self, input_stream=sys.stdin, output_stream=sys.stdout):
        output_lock = threading.Lock()
        workers = []

        def write_response(response):
            if response is None:
                return
            with output_lock:
                output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
                output_stream.flush()

        def process(request):
            write_response(self.server.handle(request))

        for line in input_stream:
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("request must be an object")
                method = request.get("method")
                if method == "tools/call" and request.get("id") is not None:
                    worker = threading.Thread(
                        target=process,
                        args=(request,),
                        daemon=True,
                    )
                    workers.append(worker)
                    worker.start()
                    continue
                response = self.server.handle(request)
            except (json.JSONDecodeError, ValueError) as error:
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": str(error)},
                }
            write_response(response)
        for worker in workers:
            worker.join(timeout=1)
