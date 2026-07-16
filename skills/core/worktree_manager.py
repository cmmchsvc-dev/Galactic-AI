import os
import subprocess
import uuid
import shutil
from skills.base import GalacticSkill

class WorktreeSkill(GalacticSkill):
    """Isolate agent sessions into separate git worktrees to prevent collisions."""

    skill_name  = "worktree_manager"
    version     = "1.0.0"
    author      = "Galactic AI"
    description = "Create isolated git worktrees for parallel agent sessions."
    category    = "system"
    icon        = "\U0001f333"

    def __init__(self, core):
        super().__init__(core)
        self.active_worktrees = {}
        # Directory to store worktrees
        self.worktree_base = os.path.join(self.core.config.get("paths", {}).get("workspace", "./workspace"), ".worktrees")
        os.makedirs(self.worktree_base, exist_ok=True)

    def get_tools(self):
        return {
            "create_worktree": {
                "description": "Create an isolated git worktree branch for safe parallel editing.",
                "parameters": {"type": "object", "properties": {
                    "branch_name": {"type": "string", "description": "Name for the new branch."},
                }, "required": ["branch_name"]},
                "fn": self._tool_create_worktree,
            },
            "remove_worktree": {
                "description": "Remove a git worktree and clean up its directory.",
                "parameters": {"type": "object", "properties": {
                    "worktree_id": {"type": "string", "description": "ID of the worktree to remove."},
                }, "required": ["worktree_id"]},
                "fn": self._tool_remove_worktree,
            },
        }

    def _is_git_repo(self):
        try:
            return subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True).returncode == 0
        except Exception:
            return False

    async def _tool_create_worktree(self, args):
        if not self._is_git_repo():
            return "[ERROR] Current directory is not a git repository. Worktrees require git."
            
        branch_name = args.get("branch_name")
        wt_id = str(uuid.uuid4())[:8]
        path = os.path.abspath(os.path.join(self.worktree_base, f"wt_{wt_id}_{branch_name}"))
        
        try:
            # Create branch and worktree
            result = subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, path],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                return f"[ERROR] Failed to create worktree: {result.stderr}"
                
            self.active_worktrees[wt_id] = {
                "id": wt_id,
                "path": path,
                "branch": branch_name
            }
            return f"Worktree created successfully.\nID: {wt_id}\nPath: {path}\nBranch: {branch_name}\n\nExecute tasks within the Path directory to keep changes isolated."
        except Exception as e:
            return f"[ERROR] {e}"

    async def _tool_remove_worktree(self, args):
        wt_id = args.get("worktree_id")
        if wt_id not in self.active_worktrees:
            return f"[ERROR] Worktree {wt_id} not found."
            
        path = self.active_worktrees[wt_id]["path"]
        try:
            # Prune git worktree
            subprocess.run(["git", "worktree", "remove", "--force", path], capture_output=True)
            # Ensure folder is deleted
            if os.path.exists(path):
                shutil.rmtree(path, ignore_errors=True)
                
            del self.active_worktrees[wt_id]
            return f"Worktree {wt_id} removed and cleaned up."
        except Exception as e:
            return f"[ERROR] {e}"
