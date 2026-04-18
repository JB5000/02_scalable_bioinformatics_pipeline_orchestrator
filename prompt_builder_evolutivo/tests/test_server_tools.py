from __future__ import annotations

from pathlib import Path

from app.server import ToolRunner


def test_write_and_read_file(tmp_path: Path) -> None:
    tools = ToolRunner(tmp_path)
    write_result = tools.write_file("notes/a.txt", "hello")
    read_result = tools.read_file("notes/a.txt", 1000)

    assert write_result["ok"] is True
    assert read_result["ok"] is True
    assert read_result["content"] == "hello"


def test_block_escape_path(tmp_path: Path) -> None:
    tools = ToolRunner(tmp_path)
    result = tools.read_file("../outside.txt", 500)

    assert result["ok"] is False


def test_run_python(tmp_path: Path) -> None:
    tools = ToolRunner(tmp_path)
    result = tools.run_python("print('ok')", 10)

    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert "ok" in result["stdout"]
