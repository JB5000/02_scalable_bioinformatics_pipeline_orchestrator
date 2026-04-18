from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlparse


DEFAULT_MODEL = "google/gemma-4-26B-A4A-it"
DEFAULT_BASE_URL = "https://api.deepinfra.com/v1/openai"


def _json_response(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _read_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def _safe_path(root: Path, user_path: str) -> Path:
    target = Path(user_path)
    if target.is_absolute():
        raise ValueError("Path must be relative")
    resolved = (root / target).resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError("Path escapes workspace")
    rel = resolved.relative_to(root_resolved).as_posix()
    if rel == ".git" or rel.startswith(".git/"):
        raise ValueError(".git access is blocked")
    return resolved


@dataclass(slots=True)
class StateStore:
    path: Path

    def ensure(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save({"messages": [], "tool_runs": []})

    def load(self) -> dict[str, Any]:
        self.ensure()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"messages": [], "tool_runs": []}
            self.save(payload)
            return payload
        payload.setdefault("messages", [])
        payload.setdefault("tool_runs", [])
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.path)


class ToolRunner:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()

    def run(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "list_files":
            return self.list_files(str(args.get("path", ".")))
        if name == "read_file":
            return self.read_file(str(args.get("path", "")), int(args.get("max_chars", 12000)))
        if name == "write_file":
            return self.write_file(str(args.get("path", "")), str(args.get("content", "")))
        if name == "run_python":
            return self.run_python(str(args.get("code", "")), int(args.get("timeout_seconds", 20)))
        if name == "run_shell":
            return self.run_shell(str(args.get("command", "")), int(args.get("timeout_seconds", 20)))
        return {"ok": False, "error": f"Unknown tool: {name}"}

    def list_files(self, path: str) -> dict[str, Any]:
        try:
            base = _safe_path(self.workspace_root, path)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if not base.exists():
            return {"ok": False, "error": "Path not found"}
        if base.is_file():
            return {"ok": True, "entries": [base.relative_to(self.workspace_root).as_posix()]}
        entries = []
        for item in sorted(base.iterdir()):
            name = item.relative_to(self.workspace_root).as_posix()
            entries.append(name + ("/" if item.is_dir() else ""))
        return {"ok": True, "entries": entries[:300]}

    def read_file(self, path: str, max_chars: int) -> dict[str, Any]:
        try:
            fpath = _safe_path(self.workspace_root, path)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if not fpath.exists() or not fpath.is_file():
            return {"ok": False, "error": "File not found"}
        content = fpath.read_text(encoding="utf-8", errors="replace")
        return {"ok": True, "path": fpath.relative_to(self.workspace_root).as_posix(), "content": content[: max(500, max_chars)]}

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        try:
            fpath = _safe_path(self.workspace_root, path)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content, encoding="utf-8")
        return {"ok": True, "path": fpath.relative_to(self.workspace_root).as_posix()}

    def run_python(self, code: str, timeout_seconds: int) -> dict[str, Any]:
        try:
            cp = subprocess.run(
                [sys.executable, "-c", code],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=max(1, timeout_seconds),
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Python timed out"}
        return {
            "ok": True,
            "exit_code": int(cp.returncode),
            "stdout": (cp.stdout or "")[:12000],
            "stderr": (cp.stderr or "")[:12000],
        }

    def run_shell(self, command: str, timeout_seconds: int) -> dict[str, Any]:
        blocked = ["sudo ", "ssh ", "scp ", "../", "rm -rf /", "git reset --hard", "git checkout --"]
        lowered = command.lower().strip()
        if any(x in lowered for x in blocked):
            return {"ok": False, "error": "Blocked by safety policy"}
        try:
            cp = subprocess.run(
                command,
                cwd=self.workspace_root,
                shell=True,
                capture_output=True,
                text=True,
                timeout=max(1, timeout_seconds),
                env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Shell timed out"}
        return {
            "ok": True,
            "exit_code": int(cp.returncode),
            "stdout": (cp.stdout or "")[:12000],
            "stderr": (cp.stderr or "")[:12000],
        }


class LLMClient:
    def __init__(self, *, api_key: str | None, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate(self, messages: list[dict[str, str]]) -> str:
        if not self.api_key:
            raise RuntimeError("DEEPINFRA_API_KEY is missing")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 800,
        }
        req = request.Request(
            f"{self.base_url}/chat/completions",
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"DeepInfra error {exc.code}: {detail}")
        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError("DeepInfra returned no choices")
        return str(choices[0].get("message", {}).get("content", "")).strip()


def _parse_llm_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3 and lines[-1].startswith("```"):
            raw = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"type": "reply", "content": text.strip()}
    if not isinstance(parsed, dict):
        return {"type": "reply", "content": text.strip()}
    return parsed


def _agent_reply(message: str, llm: LLMClient, tools: ToolRunner) -> tuple[str, list[dict[str, Any]]]:
    system_prompt = (
        "You are Jones, a coding assistant. Reply in Portuguese (Portugal). "
        "Use tools when useful. Output ONLY JSON: "
        "{'type':'reply','content':'...'} or {'type':'tool','tool':'list_files|read_file|write_file|run_python|run_shell','args':{...}}"
    )
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": message}]
    runs: list[dict[str, Any]] = []

    for _ in range(6):
        model_out = llm.generate(messages)
        parsed = _parse_llm_json(model_out)
        if parsed.get("type") != "tool":
            return str(parsed.get("content", model_out)).strip(), runs

        tool_name = str(parsed.get("tool", "")).strip()
        args = parsed.get("args", {})
        if not isinstance(args, dict):
            args = {}
        result = tools.run(tool_name, args)
        runs.append({"tool": tool_name, "args": args, "result": result})
        messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
        messages.append(
            {
                "role": "user",
                "content": "TOOL_RESULT:\n" + json.dumps(result, ensure_ascii=False) + "\nIf done, answer with type=reply.",
            }
        )
    return "Cheguei ao limite de passos automáticos; diz-me o próximo passo e continuo.", runs


def _ui_html() -> str:
    return """<!doctype html>
<html lang=\"pt\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Jones Chat</title>
  <style>
    :root { --bg:#0b1220; --panel:#101a2f; --text:#eef3ff; --muted:#9dadcd; --border:rgba(148,163,184,.2); --u:rgba(88,197,255,.12); --a:rgba(120,255,174,.1); }
    * { box-sizing:border-box; }
    body { margin:0; background:linear-gradient(180deg,#07101d,#0b1220); color:var(--text); font-family:Inter,system-ui,sans-serif; }
    .wrap { max-width:920px; margin:0 auto; padding:16px; }
    .card { background:var(--panel); border:1px solid var(--border); border-radius:16px; overflow:hidden; }
    .head { padding:12px 14px; border-bottom:1px solid var(--border); }
    .chat { height:62vh; min-height:380px; overflow:auto; padding:12px; display:flex; flex-direction:column; gap:10px; }
    .b { border:1px solid var(--border); border-radius:12px; padding:10px; max-width:86%; white-space:pre-wrap; word-break:break-word; }
    .u { align-self:flex-end; background:var(--u); }
    .a { align-self:flex-start; background:var(--a); }
    .meta { color:var(--muted); font-size:12px; margin-bottom:4px; }
    .composer { border-top:1px solid var(--border); display:grid; grid-template-columns:1fr 130px; gap:10px; padding:10px; }
    textarea { width:100%; min-height:90px; border-radius:10px; border:1px solid var(--border); background:rgba(255,255,255,.03); color:var(--text); padding:10px; }
    button { border:0; border-radius:10px; background:#58c5ff; color:#06101d; font-weight:700; cursor:pointer; }
    details { margin-top:10px; border:1px solid var(--border); border-radius:10px; padding:8px; }
    summary { color:var(--muted); cursor:pointer; }
    pre { margin:8px 0 0; border:1px solid var(--border); border-radius:8px; background:rgba(0,0,0,.2); padding:8px; max-height:240px; overflow:auto; }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"card\">
      <div class=\"head\">Jones - chat normal com Gemma 4 26B (DeepInfra)</div>
      <div id=\"chat\" class=\"chat\"></div>
      <div class=\"composer\">
        <textarea id=\"msg\" placeholder=\"Escreve aqui...\"></textarea>
        <button id=\"send\">Enviar</button>
      </div>
    </div>
    <details>
      <summary>Tools (opcional)</summary>
      <pre id=\"tools\">Sem atividade.</pre>
    </details>
  </div>
  <script>
    function esc(t){return String(t).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');}
    function render(messages){
      const c=document.getElementById('chat');
      if(!messages.length){c.innerHTML='<div style="color:#9dadcd">Começa a conversa.</div>';return;}
      c.innerHTML=messages.map(m=>`<div class=\"b ${m.role==='user'?'u':'a'}\"><div class=\"meta\">${esc(m.role)} - ${esc(m.timestamp||'')}</div>${esc(m.content||'')}</div>`).join('');
      c.scrollTop=c.scrollHeight;
    }
    async function refresh(){
      const s=await (await fetch('/api/state')).json();
      render(s.messages||[]);
      document.getElementById('tools').textContent=JSON.stringify(s.tool_runs||[],null,2);
    }
    async function send(){
      const box=document.getElementById('msg');
      const message=box.value.trim();
      if(!message) return;
      await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message})});
      box.value='';
      await refresh();
    }
    document.getElementById('send').addEventListener('click',send);
    refresh();
    setInterval(refresh,1500);
  </script>
</body>
</html>"""


def build_app(config: PromptBuilderConfig, store: StateStore):
    tools = ToolRunner(config.project_root)
    llm = LLMClient(
        api_key=os.environ.get("DEEPINFRA_API_KEY"),
        base_url=os.environ.get("PROMPT_BUILDER_BASE_URL", DEFAULT_BASE_URL),
        model=os.environ.get("PROMPT_BUILDER_MODEL", DEFAULT_MODEL),
    )

    class Handler(BaseHTTPRequestHandler):
        server_version = "JonesSimple/1.0"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                html = _ui_html().encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return
            if parsed.path == "/api/state":
                _json_response(self, store.load())
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/clear":
                payload = {"messages": [], "tool_runs": []}
                store.save(payload)
                _json_response(self, payload)
                return
            if parsed.path != "/api/chat":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                body = _read_body(self)
            except json.JSONDecodeError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON")
                return
            msg = str(body.get("message", "")).strip()
            if not msg:
                self.send_error(HTTPStatus.BAD_REQUEST, "Missing message")
                return
            payload = store.load()
            payload["messages"].append({"role": "user", "content": msg, "timestamp": utc_now_iso()})
            try:
                reply, tool_runs = _agent_reply(msg, llm, tools)
            except Exception as exc:
                reply = f"Erro: {exc}"
                tool_runs = []
            payload["messages"].append({"role": "assistant", "content": reply, "timestamp": utc_now_iso()})
            payload["tool_runs"] = (payload.get("tool_runs", []) + tool_runs)[-50:]
            store.save(payload)
            _json_response(self, payload, HTTPStatus.ACCEPTED)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return Handler


def run_server(*, host: str, port: int, backend: str) -> None:
    del backend
    load_env_file()
    config = PromptBuilderConfig()
    config.runtime_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    store = StateStore(config.runtime_dir / "jones_state.json")
    store.ensure()
    app = build_app(config, store)
    httpd = ThreadingHTTPServer((host, port), app)
    print(f"Jones simple chat running on http://{host}:{port}")
    httpd.serve_forever()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="jones-web", description="Simple Jones web chat")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--backend", choices=["mock", "deepinfra"], default="deepinfra")
    args = parser.parse_args(argv)
    run_server(host=args.host, port=args.port, backend=args.backend)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
