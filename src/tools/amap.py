
import asyncio
import os
import json
from typing import Optional, Type, AsyncGenerator
from contextlib import asynccontextmanager
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

class AmapRouteSchema(BaseModel):
    origin: str = Field(description="Start location (e.g. 'Beijing Station' or coordinates)")
    destination: str = Field(description="End location (e.g. 'Forbidden City' or coordinates)")

class AmapRouteTool(BaseTool):
    name: str = "amap_route"
    description: str = "Calculate route distance and duration using Amap via MCP."
    args_schema: Type[BaseModel] = AmapRouteSchema

    def _run(self, origin: str, destination: str) -> str:
        """Synchronous wrapper for the async MCP call."""
        try:
            return asyncio.run(self._arun(origin, destination))
        except Exception as e:
            return f"Error running MCP tool: {str(e)}"

    @asynccontextmanager
    async def _get_mcp_session(self):
        """
        Context manager to yield an initialized MCP session.
        Supports both SSE (HTTP) and Stdio (Local Process) connections.
        """
        mcp_url = os.getenv("AMAP_MCP_URL")
        mcp_command = os.getenv("AMAP_MCP_COMMAND")
        
        if mcp_url:
            # Case 1: SSE (HTTP) Connection
            headers = {}
            # If using DashScope MCP, we might need Authorization header
            # Usually the key is passed via URL query params or headers
            dashscope_key = os.getenv("OPENAI_API_KEY") # Reusing the key variable if it's DashScope
            if dashscope_key and "dashscope" in mcp_url:
                 headers["Authorization"] = f"Bearer {dashscope_key}"

            async with sse_client(mcp_url, headers=headers) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
        elif mcp_command:
            # Case 2: Stdio (Local Process) Connection
            args = os.getenv("AMAP_MCP_ARGS", "").split()
            server_params = StdioServerParameters(
                command=mcp_command,
                args=args,
                env=os.environ.copy()
            )
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
        else:
            raise ValueError("No MCP configuration found (AMAP_MCP_URL or AMAP_MCP_COMMAND)")

    async def _arun(self, origin: str, destination: str) -> str:
        """
        Connects to the configured MCP server and calls the route tool.
        """
        tool_name = os.getenv("AMAP_MCP_TOOL_NAME", "amap_route")

        try:
            async with self._get_mcp_session() as session:
                # Call the tool
                result = await session.call_tool(
                    tool_name,
                    arguments={"origin": origin, "destination": destination}
                )
                
                if result.content and hasattr(result.content[0], "text"):
                    return result.content[0].text
                return str(result.content)

        except ValueError as ve:
            # Fallback for dev/demo if no configuration
            return json.dumps({
                "error": str(ve),
                "origin": origin,
                "destination": destination,
                "distance_km": 0,
                "duration_minutes": 0
            })
        except Exception as e:
            return json.dumps({"error": f"MCP Connection Failed: {str(e)}"})

class AmapPoiSearchTool(BaseTool):
    name: str = "amap_poi_search"
    description: str = "Search for POI details via MCP."

    def _run(self, keyword: str, city: str = "") -> str:
        return asyncio.run(self._arun(keyword, city))
    
    async def _arun(self, keyword: str, city: str = "") -> str:
        # Placeholder implementation
        return json.dumps({"message": "POI Search via MCP not yet implemented in this demo"})
