# Self-Evolving Solver (DeepInfra gpt-oss-120b)

This module provides an interactive coding solver that can:
- chat with the user while solving tasks,
- read and write files in the workspace,
- run shell and Python commands,
- store persistent learning episodes and strategy notes.

## Run

```bash
cd /home/jonyb/python_folder
export DEEPINFRA_API_KEY="your_key_here"
.venv/bin/python self_evolving_solver.py --model gpt-oss-120b
```

## Files

- `self_evolving_solver.py`: interactive CLI entrypoint.
- `src/solver/deepinfra_client.py`: DeepInfra chat completion client.
- `src/solver/tools.py`: bounded local tool execution.
- `src/solver/memory_store.py`: persistent episode/policy storage.
- `src/solver/agent.py`: iterative solver loop with reflection.
- `src/solver/__init__.py`: package exports.

## Memory

A `.solver_state/` directory is created in the workspace:
- `policy.md`: current solver strategy and appended heuristics.
- `episodes.jsonl`: compact history of solved episodes.

## Safety

The shell runner blocks clearly destructive command patterns and constrains file operations to the workspace path.
