# src/tools/http.py

import json
import os
import uuid
from typing import Any, Dict, Optional

import httpx


class McpStreamableHttpClient:
    """MCP Streamable HTTP Client with debugging"""

    def __init__(self, endpoint: str, timeout_s: float = 60.0, debug: bool = None):
        self._endpoint = endpoint
        self._client = httpx.Client(timeout=timeout_s)
        self._session_id: Optional[str] = None
        self._initialized = False
        self.headers: Dict[str, str] = {}
        
        # 调试模式
        if debug is None:
            self._debug = os.getenv("MCP_DEBUG", "").lower() in ("true", "1", "yes")
        else:
            self._debug = debug

    def _log(self, msg: str, data: Any = None):
        """调试日志"""
        if not self._debug:
            return
        if data is not None:
            try:
                if isinstance(data, (dict, list)):
                    data_str = json.dumps(data, ensure_ascii=False)[:500]
                else:
                    data_str = str(data)[:500]
                print(f"[MCP DEBUG] {msg}: {data_str}")
            except:
                print(f"[MCP DEBUG] {msg}: {data}")
        else:
            print(f"[MCP DEBUG] {msg}")

    def close(self) -> None:
        self._client.close()

    def _parse_sse_response(self, response: httpx.Response, request_id: str) -> Dict[str, Any]:
        """Parse Server-Sent Events response."""
        last_obj: Optional[Dict[str, Any]] = None
        
        self._log("Parsing SSE response", {"status": response.status_code})
        
        for line in response.iter_lines():
            if not line:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="ignore")
            
            line = line.strip()
            self._log("SSE line", line[:200])
            
            if not line.startswith("data:"):
                continue
                
            data = line[5:].strip()
            if not data:
                continue
                
            try:
                obj = json.loads(data)
                last_obj = obj
                if isinstance(obj, dict):
                    if obj.get("id") == request_id and ("result" in obj or "error" in obj):
                        self._log("Found matching response", obj)
                        return obj
            except json.JSONDecodeError as e:
                self._log(f"JSON decode error: {e}", data[:100])
                continue
                
        if last_obj is not None:
            return last_obj
        raise RuntimeError("MCP SSE response parsing failed - no valid data received")

    def _post_jsonrpc(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Send JSON-RPC request to MCP server."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.headers:
            headers.update(self.headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        self._log("Request URL", self._endpoint)
        self._log("Request headers", {k: v[:20] + "..." if len(str(v)) > 20 else v for k, v in headers.items()})
        self._log("Request body", msg)

        try:
            response = self._client.post(self._endpoint, json=msg, headers=headers)
        except httpx.ConnectError as e:
            raise RuntimeError(f"无法连接到 MCP 服务器 {self._endpoint}: {e}")
        except httpx.TimeoutException as e:
            raise RuntimeError(f"MCP 请求超时: {e}")

        self._log("Response status", response.status_code)
        self._log("Response headers", dict(response.headers))

        if response.status_code == 404 and self._session_id:
            self._session_id = None
            self._initialized = False
            
        if response.status_code >= 400:
            response_text = response.text[:500] if response.text else "(empty)"
            self._log("Error response", response_text)
            raise RuntimeError(f"MCP HTTP {response.status_code}: {response_text}")

        new_session_id = response.headers.get("mcp-session-id") or response.headers.get("Mcp-Session-Id")
        if new_session_id:
            self._session_id = new_session_id
            self._log("New session ID", new_session_id)

        content_type = (response.headers.get("content-type") or "").lower()
        self._log("Content-Type", content_type)
        
        if "text/event-stream" in content_type:
            return self._parse_sse_response(response, msg.get("id"))
        
        # 检查响应是否为空
        response_text = response.text.strip()
        if not response_text:
            raise RuntimeError("MCP 返回空响应")
        
        self._log("Response body", response_text[:500])
        
        try:
            return response.json()
        except json.JSONDecodeError as e:
            # 可能是 HTML 错误页面
            if response_text.startswith("<!") or response_text.startswith("<html"):
                raise RuntimeError(f"MCP 返回了 HTML 而非 JSON，可能是 URL 错误或服务不可用")
            raise RuntimeError(f"MCP 响应 JSON 解析失败: {e}, 响应内容: {response_text[:200]}")

    def initialize(self) -> bool:
        """Initialize MCP session."""
        if self._initialized:
            return True

        self._log("Initializing MCP connection", self._endpoint)

        init_msg = {
            "jsonrpc": "2.0",
            "id": "init-0",
            "method": "initialize",
            "params": {
                "protocolVersion": os.getenv("MCP_PROTOCOL_VERSION", "2025-03-26"),
                "capabilities": {},
                "clientInfo": {"name": "travelAgent-backend", "version": "0.1.0"},
            },
        }

        try:
            result = self._post_jsonrpc(init_msg)
            self._log("Initialize result", result)
            self._initialized = True
            
            # Send initialized notification
            if self._session_id:
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                }
                if self.headers:
                    headers.update(self.headers)
                headers["Mcp-Session-Id"] = self._session_id

                self._client.post(
                    self._endpoint,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                    headers=headers,
                )
            
            self._log("MCP initialized successfully")
            return True
        except Exception as e:
            print(f"❌ MCP initialization failed: {e}")
            import traceback
            if self._debug:
                traceback.print_exc()
            return False

    def call_tool(self, tool_name: str = None, arguments: Dict[str, Any] = None, *, name: str = None) -> Any:
        """Call an MCP tool."""
        actual_name = tool_name or name
        if actual_name is None:
            raise ValueError("tool_name is required")
        
        if arguments is None:
            arguments = {}
        
        self._log(f"Calling tool: {actual_name}", arguments)
        
        if not self._initialized:
            if not self.initialize():
                raise RuntimeError("MCP 初始化失败，无法调用工具")

        request_id = uuid.uuid4().hex
        msg = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": actual_name, "arguments": arguments},
        }

        response = self._post_jsonrpc(msg)

        if isinstance(response, dict) and "error" in response:
            error_info = response['error']
            raise RuntimeError(f"MCP tool error: {error_info}")

        result = self._extract_result(response)
        self._log("Tool result", result)
        return result

    def _extract_result(self, resp_obj: Any) -> Any:
        """Extract result from JSON-RPC response."""
        if not isinstance(resp_obj, dict) or "result" not in resp_obj:
            return resp_obj

        result = resp_obj["result"]
        
        if isinstance(result, dict) and isinstance(result.get("content"), list):
            texts = []
            for item in result["content"]:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    texts.append(item["text"])
            
            if texts:
                combined_text = "".join(texts).strip()
                try:
                    return json.loads(combined_text)
                except json.JSONDecodeError:
                    return combined_text
                    
        return result

    def list_tools(self) -> list:
        """列出可用的工具"""
        if not self._initialized:
            if not self.initialize():
                return []

        request_id = uuid.uuid4().hex
        msg = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/list",
            "params": {},
        }

        try:
            response = self._post_jsonrpc(msg)
            
            if isinstance(response, dict) and "result" in response:
                return response["result"].get("tools", [])
        except Exception as e:
            self._log(f"List tools failed: {e}")
        
        return []