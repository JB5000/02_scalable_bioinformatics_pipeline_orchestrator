# Jones Simple Web Chat

[2026-04-21] - Rebuilt project as a minimal web chat with DeepInfra Gemma and only essential coding tools - to keep a normal interface and practical code assistance.

## What this is

A single web page where you chat with an LLM (DeepInfra Gemma by default).
The assistant can use only essential tools:

- `list_files`
- `read_file`
- `write_file`
- `run_python`
- `run_shell`

## Run

```bash
cd /home/jonyb/python_folder/prompt_builder_evolutivo
source /home/jonyb/python_folder/.venv/bin/activate
export DEEPINFRA_API_KEY="YOUR_KEY"
python -m app jones-web --backend deepinfra --host 127.0.0.1 --port 8010
```

Open: `http://127.0.0.1:8010`

## Safety

- Tools are constrained to workspace-relative paths.
- `.git` access is blocked.
- Unsafe shell patterns are blocked.
