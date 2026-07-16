import os
import shutil
from datetime import datetime
from pathlib import Path
from skills.base import GalacticSkill

class VCRThinkbackSkill(GalacticSkill):
    """
    The VCR & Thinkback Skill (Time Travel)
    Allows backing up files before major edits and restoring them (undo).
    """
    skill_name = "vcr_thinkback"
    version = "1.0.0"
    author = "Galactic AI"
    description = "Provides file-level snapshots and undo capabilities for AI actions."
    category = "safety"
    icon = "⏪"

    def __init__(self, core):
        super().__init__(core)
        self.vcr_dir = Path(self.core.config.get("paths", {}).get("workspace", "./workspace")) / ".galactic_vcr"
        self.vcr_dir.mkdir(parents=True, exist_ok=True)

    def get_tools(self):
        return {
            "vcr_snapshot": {
                "description": "Take a backup snapshot of a file before modifying it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to the file to backup."}
                    },
                    "required": ["file_path"]
                },
                "fn": self._tool_snapshot
            },
            "vcr_undo": {
                "description": "Restore a file to its last VCR snapshot.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to the file to restore."}
                    },
                    "required": ["file_path"]
                },
                "fn": self._tool_undo
            },
            "vcr_list_snapshots": {
                "description": "List available VCR snapshots for a given file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to the file."}
                    },
                    "required": ["file_path"]
                },
                "fn": self._tool_list
            }
        }

    async def _tool_snapshot(self, args):
        file_path = Path(args.get("file_path"))
        if not file_path.exists():
            return f"[ERROR] File {file_path} does not exist."
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = f"{file_path.name}_{timestamp}.bak"
        backup_path = self.vcr_dir / safe_name
        
        shutil.copy2(file_path, backup_path)
        
        # Save a mapping
        mapping_file = self.vcr_dir / "mapping.txt"
        with open(mapping_file, "a") as f:
            f.write(f"{file_path}|{backup_path}\n")
            
        return f"VCR Snapshot taken: {backup_path.name}. You can restore this using vcr_undo."

    async def _tool_undo(self, args):
        file_path = str(Path(args.get("file_path")))
        mapping_file = self.vcr_dir / "mapping.txt"
        
        if not mapping_file.exists():
            return "[ERROR] No VCR snapshots found."
            
        # Read mappings in reverse to get the latest
        lines = mapping_file.read_text().splitlines()
        latest_backup = None
        for line in reversed(lines):
            orig, backup = line.split("|", 1)
            if orig == file_path:
                latest_backup = backup
                break
                
        if not latest_backup or not Path(latest_backup).exists():
            return f"[ERROR] No valid backup found for {file_path}"
            
        shutil.copy2(latest_backup, file_path)
        return f"⏪ Rewind successful. Restored {file_path} to previous state from {Path(latest_backup).name}."

    async def _tool_list(self, args):
        file_path = str(Path(args.get("file_path")))
        mapping_file = self.vcr_dir / "mapping.txt"
        
        if not mapping_file.exists():
            return "No snapshots available."
            
        backups = []
        for line in mapping_file.read_text().splitlines():
            orig, backup = line.split("|", 1)
            if orig == file_path:
                backups.append(Path(backup).name)
                
        if not backups:
            return f"No backups for {file_path}."
            
        return "Available snapshots:\n" + "\n".join(f"- {b}" for b in backups)
