const vscode = require('vscode');

function activate(context) {
  const command = vscode.commands.registerCommand('gptOss120b.openChat', () => {
    const panel = vscode.window.createWebviewPanel(
      'gptOss120b.chat',
      'GPT OSS 120B Chat',
      vscode.ViewColumn.Beside,
      {
        enableScripts: true,
        retainContextWhenHidden: true
      }
    );

    panel.webview.html = getWebviewHtml(panel.webview, context.extensionUri);

    const history = [];

    panel.webview.onDidReceiveMessage(async (message) => {
      if (!message || typeof message !== 'object') {
        return;
      }

      if (message.type === 'ask') {
        const userText = String(message.text || '').trim();
        if (!userText) {
          return;
        }

        history.push({ role: 'user', content: userText });
        panel.webview.postMessage({ type: 'status', text: 'A perguntar ao modelo...' });

        try {
          const answer = await requestCompletion(history);
          history.push({ role: 'assistant', content: answer });
          panel.webview.postMessage({ type: 'answer', text: answer });
        } catch (error) {
          const errText = error instanceof Error ? error.message : String(error);
          panel.webview.postMessage({ type: 'error', text: errText });
        }
      }

      if (message.type === 'reset') {
        history.length = 0;
        panel.webview.postMessage({ type: 'status', text: 'Historico limpo.' });
      }
    });
  });

  context.subscriptions.push(command);
}

async function requestCompletion(history) {
  const config = vscode.workspace.getConfiguration('gptOss120b');
  const apiKey = config.get('deepinfraApiKey') || process.env.DEEPINFRA_API_KEY || '';
  const model = config.get('model', 'gpt-oss-120b');
  const baseUrl = config.get('baseUrl', 'https://api.deepinfra.com/v1/openai');
  const systemPrompt = config.get(
    'systemPrompt',
    'You are a helpful coding assistant. Give practical answers and concise code snippets.'
  );
  const temperature = config.get('temperature', 0.2);
  const maxTokens = config.get('maxTokens', 1400);

  if (!apiKey) {
    throw new Error('Missing API key. Set gptOss120b.deepinfraApiKey or DEEPINFRA_API_KEY.');
  }

  const url = `${String(baseUrl).replace(/\/$/, '')}/chat/completions`;
  const messages = [{ role: 'system', content: String(systemPrompt) }, ...history];

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      model,
      messages,
      temperature,
      max_tokens: maxTokens
    })
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`DeepInfra error ${response.status}: ${body.slice(0, 600)}`);
  }

  const payload = await response.json();
  const text = payload?.choices?.[0]?.message?.content;
  if (!text || typeof text !== 'string') {
    throw new Error('Invalid response payload from DeepInfra.');
  }

  return text.trim();
}

function getWebviewHtml(webview, extensionUri) {
  const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'media', 'chat.js'));
  const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'media', 'chat.css'));
  const nonce = String(Date.now());

  return `<!DOCTYPE html>
<html lang="pt">
  <head>
    <meta charset="UTF-8" />
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="stylesheet" href="${styleUri}" />
    <title>GPT OSS 120B Chat</title>
  </head>
  <body>
    <header>
      <h1>GPT OSS 120B</h1>
      <button id="resetBtn" title="Limpar histórico">Reset</button>
    </header>

    <main id="messages"></main>

    <footer>
      <textarea id="input" placeholder="Escreve a tua pergunta..." rows="4"></textarea>
      <button id="sendBtn">Enviar</button>
    </footer>

    <script nonce="${nonce}" src="${scriptUri}"></script>
  </body>
</html>`;
}

function deactivate() {}

module.exports = {
  activate,
  deactivate
};
