const vscode = acquireVsCodeApi();

const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('input');
const sendBtn = document.getElementById('sendBtn');
const resetBtn = document.getElementById('resetBtn');

function appendMessage(role, text) {
  const item = document.createElement('div');
  item.className = `msg ${role}`;
  item.textContent = text;
  messagesEl.appendChild(item);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function ask() {
  const text = inputEl.value.trim();
  if (!text) {
    return;
  }

  appendMessage('user', text);
  inputEl.value = '';
  vscode.postMessage({ type: 'ask', text });
}

sendBtn.addEventListener('click', ask);
resetBtn.addEventListener('click', () => {
  messagesEl.innerHTML = '';
  vscode.postMessage({ type: 'reset' });
});

inputEl.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    ask();
  }
});

window.addEventListener('message', (event) => {
  const message = event.data;
  if (!message) {
    return;
  }

  if (message.type === 'answer') {
    appendMessage('assistant', message.text);
  }

  if (message.type === 'error') {
    appendMessage('error', message.text);
  }

  if (message.type === 'status') {
    appendMessage('status', message.text);
  }
});

appendMessage('status', 'Pronto. Usa Ctrl+Enter para enviar.');
