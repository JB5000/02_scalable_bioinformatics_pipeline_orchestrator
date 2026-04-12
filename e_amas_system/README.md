# E-AMAS

[2026-04-13] - Implementado um subprojeto autocontido `e_amas_system` com Manager, Worker Swarm, Knowledge Ledger, Adversary, métricas e treino competitivo - para testar batching intensivo e auto-melhoria sem mexer no snapshot antigo do repositório.

E-AMAS é um protótipo em Python para coordenar múltiplos workers sobre um backend compatível com OpenAI/vLLM, usando `asyncio`, memória em JSON e um loop adversarial de treino.

## Componentes

- `BatchManager`: planeia o batch, evolui prompts, faz crítica/consenso e escreve post-mortems.
- `WorkerSwarm`: dispara workers em paralelo para favorecer continuous batching no backend.
- `KnowledgeLedger`: guarda episódios e notas em JSON.
- `ProgressiveAdversary`: gera problemas com dificuldade progressiva e ground truth conhecido.
- `CompetitionTrainer`: põe duas equipas a competir e transfere lições da vencedora.
- `BatchMetricsLogger`: regista tokens, latência, qualidade e eficiência em JSONL.

## Estrutura

- `e_amas/`: package principal
- `tests/`: testes locais
- `runtime/`: ledgers, métricas e resumos gerados em execução
- `e_amas.log`: log do sistema

## Execução

Corrida local com backend mock:

```bash
cd /home/jonyb/python_folder/e_amas_system
python -m e_amas --backend mock run-episode --team-name TeamA
python -m e_amas --backend mock train-competition --rounds 6
```

Execução real contra `vLLM` em modo OpenAI-compatible:

```bash
cd /home/jonyb/python_folder/e_amas_system
python -m e_amas --backend openai train-competition \
  --model google/gemma-2-27b-it \
  --base-url http://127.0.0.1:8000/v1 \
  --rounds 8
```

Testes locais:

```bash
cd /home/jonyb/python_folder/e_amas_system
python -m unittest discover -s tests -v
```

## Notas de design

- O continuous batching do `vLLM` é explorado enviando pedidos concorrentes via `asyncio`.
- O backend `mock` existe para desenvolvimento offline e testes determinísticos.
- A métrica usada é `E = qualidade / (tokens * tempo)`.
- Os prompts dos workers evoluem a partir das notas recentes do ledger para cada família de desafio.
