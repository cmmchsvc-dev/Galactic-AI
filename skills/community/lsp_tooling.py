import asyncio
import json
from skills.base import GalacticSkill

class NativeLSPSkill(GalacticSkill):
    """
    Native LSP (Language Server Protocol) Tooling Simulation
    Provides syntax-aware code intelligence (find definition, references) using AST/Jedi.
    """
    skill_name = "lsp_tooling"
    version = "1.0.0"
    author = "Galactic AI"
    description = "Provides deep code intelligence using AST parsing instead of regex."
    category = "coding"
    icon = "🔬"

    def __init__(self, core):
        super().__init__(core)

    def get_tools(self):
        return {
            "lsp_get_definitions": {
                "description": "Get the definition location of a class or function in a Python file using AST.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to the Python file."},
                        "target_name": {"type": "string", "description": "Name of the class or function to find."}
                    },
                    "required": ["file_path", "target_name"]
                },
                "fn": self._tool_get_definition
            },
            "lsp_extract_symbol": {
                "description": "Extract the full source code of a specific class or function from a Python file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to the Python file."},
                        "target_name": {"type": "string", "description": "Name of the class or function to extract."}
                    },
                    "required": ["file_path", "target_name"]
                },
                "fn": self._tool_extract_symbol
            }
        }

    async def _tool_get_definition(self, args):
        import ast
        file_path = args.get("file_path")
        target_name = args.get("target_name")
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source)
        except Exception as e:
            return f"[ERROR] Failed to parse AST for {file_path}: {e}"
            
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == target_name:
                    return f"Found '{target_name}' at line {node.lineno} in {file_path}."
                    
        return f"Could not find definition for '{target_name}' in {file_path}."

    async def _tool_extract_symbol(self, args):
        import ast
        file_path = args.get("file_path")
        target_name = args.get("target_name")
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source)
            lines = source.splitlines()
        except Exception as e:
            return f"[ERROR] Failed to parse AST for {file_path}: {e}"
            
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == target_name:
                    start = node.lineno - 1
                    end = node.end_lineno
                    snippet = "\n".join(lines[start:end])
                    return f"### Extracted `{target_name}` from `{file_path}`:\n```python\n{snippet}\n```"
                    
        return f"Could not find symbol '{target_name}' in {file_path}."
