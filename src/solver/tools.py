"""Tool execution layer used by the solver agent."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


FORBIDDEN_SHELL_PATTERNS = [
    "rm -rf /",
    "mkfs",
    "shutdown",
    "reboot",
    ":(){:|:&};:",
]


@dataclass
class LocalToolExecutor:
    """Execute bounded local actions for coding tasks."""

    workspace: Path

    def _resolve_path(self, path: str) -> Path:
        resolved = (self.workspace / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        workspace_resolved = self.workspace.resolve()
        if workspace_resolved not in resolved.parents and resolved != workspace_resolved:
            raise ValueError(f"Path outside workspace is not allowed: {resolved}")
        return resolved

    def read_file(self, path: str, max_chars: int = 8000) -> Dict[str, object]:
        target = self._resolve_path(path)
        if not target.exists():
            return {"ok": False, "error": f"File not found: {target}"}
        if target.is_dir():
            return {"ok": False, "error": f"Path is directory: {target}"}
        content = target.read_text(encoding="utf-8", errors="replace")
        return {
            "ok": True,
            "path": str(target),
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
        }

    def write_file(self, path: str, content: str, append: bool = False) -> Dict[str, object]:
        target = self._resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with target.open(mode, encoding="utf-8") as handle:
            handle.write(content)
        return {"ok": True, "path": str(target), "bytes": len(content.encode("utf-8"))}

    def run_shell(self, command: str, timeout_seconds: int = 120) -> Dict[str, object]:
        lowered = command.lower()
        if any(token in lowered for token in FORBIDDEN_SHELL_PATTERNS):
            return {"ok": False, "error": "Command blocked by safety policy"}
        try:
            result = subprocess.run(
                command,
                cwd=str(self.workspace),
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Command timed out after {timeout_seconds}s"}

        return {
            "ok": result.returncode == 0,
            "command": command,
            "exit_code": result.returncode,
            "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-12000:],
        }

    def run_python(self, code: str, timeout_seconds: int = 120) -> Dict[str, object]:
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Python timed out after {timeout_seconds}s"}

        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-12000:],
        }

    def execute(self, action: str, params: Dict[str, object]) -> Dict[str, object]:
        """Dispatch action to the matching tool."""
        if action == "read_file":
            return self.read_file(
                path=str(params.get("path", "")),
                max_chars=int(params.get("max_chars", 8000)),
            )
        if action == "write_file":
            return self.write_file(
                path=str(params.get("path", "")),
                content=str(params.get("content", "")),
                append=bool(params.get("append", False)),
            )
        if action == "run_shell":
            return self.run_shell(
                command=str(params.get("command", "")),
                timeout_seconds=int(params.get("timeout_seconds", 120)),
            )
        if action == "run_python":
            return self.run_python(
                code=str(params.get("code", "")),
                timeout_seconds=int(params.get("timeout_seconds", 120)),
            )
        return {"ok": False, "error": f"Unknown action: {action}"}
