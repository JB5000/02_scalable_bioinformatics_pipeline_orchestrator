# GPT OSS 120B Chat (VS Code Extension)

A lightweight VS Code extension that works like a simple Copilot-style chat panel, but uses DeepInfra with `gpt-oss-120b`.

## Features

- command: `GPT OSS 120B: Open Chat`
- interactive chat panel in a webview
- configurable model, temperature, max tokens
- API key via VS Code settings or environment variable

## Prerequisites

- Node.js 18+ and npm
- VS Code 1.85+
- DeepInfra API key

## Setup

1. Open this extension folder in VS Code:
   - `/home/jonyb/python_folder/custom_gpt_oss_120b_IDE`
2. Install dependencies:

```bash
npm install
```

3. Press `F5` to launch the Extension Development Host.
4. In the new VS Code window, run command palette:
   - `GPT OSS 120B: Open Chat`

## Configuration

Set one of these:

- VS Code setting: `gptOss120b.deepinfraApiKey`
- Environment variable: `DEEPINFRA_API_KEY`

Optional settings:

- `gptOss120b.model` (default: `gpt-oss-120b`)
- `gptOss120b.baseUrl` (default: `https://api.deepinfra.com/v1/openai`)
- `gptOss120b.systemPrompt`
- `gptOss120b.temperature`
- `gptOss120b.maxTokens`

## Notes

- This is an MVP extension, focused on chat workflow only.
- Next upgrades can include code actions, file edits, terminal tools, and streaming tokens.
