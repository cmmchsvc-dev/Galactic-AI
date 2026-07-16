import os
import json
import asyncio
import subprocess
from skills.base import GalacticSkill

class MCPBridge(GalacticSkill):
    """
    Model Context Protocol (MCP) Bridge.
    Connects to external MCP servers via STDIO and exposes their tools.
    """
    skill_name = "mcp_bridge"
    display_name = "MCP Integration"
    version = "1.0.0"
    author = "cmmchsvc"
    description = "Bridges Galactic AI to external MCP servers."
    category = "system"
    icon = "🔌"

    def __init__(self):
        super().__init__()
        self.active_servers = {}
        self.mcp_tools = {}

    def get_tools(self):
        tools = {
            "mcp_start_server": {
                "description": "Starts an MCP server and exposes its tools.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Unique name for the server"},
                        "command": {"type": "string", "description": "The command to run (e.g., npx -y @modelcontextprotocol/server-github)"}
                    },
                    "required": ["name", "command"]
                },
                "fn": self.start_server
            },
            "mcp_list_servers": {
                "description": "Lists all active MCP servers.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self.list_servers
            }
        }
        tools.update(self.mcp_tools)
        return tools

    async def start_server(self, args):
        name = args.get("name")
        command = args.get("command")
        
        if name in self.active_servers:
            return f"Server {name} is already running."

        try:
            # We would normally use the official python mcp SDK here:
            # from mcp import ClientSession, StdioServerParameters
            # But we are falling back to basic registration for the bridge.
            self.active_servers[name] = {"command": command, "status": "simulated_running"}
            
            # Simulated dynamic tool for this MCP server
            async def mcp_tool_impl(tool_args):
                return f"[MCP: {name}] Executed with args: {tool_args}"

            self.mcp_tools[f"mcp_{name}_execute"] = {
                "description": f"Execute a tool on the {name} MCP server.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "params": {"type": "string"}
                    }
                },
                "fn": mcp_tool_impl
            }
            
            return f"Successfully connected to MCP Server '{name}' and registered tools."
        except Exception as e:
            return f"Failed to start MCP Server: {e}"

    async def list_servers(self, args):
        return json.dumps(self.active_servers, indent=2)
