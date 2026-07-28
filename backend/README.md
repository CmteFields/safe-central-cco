# Backend RAG

Serviço local que combina recuperação no grafo SAFE com interpretação pelo Gemini.

## Executar

Configure `GEMINI_API_KEY` nas variáveis de ambiente e execute, a partir de `PortalCCO`:

```powershell
python backend/server.py
```

O serviço ficará disponível em `http://127.0.0.1:8765`. O portal tenta essa API primeiro e mantém a busca textual como fallback.

Cada resposta registra no banco único `portalcco.db`:

- a pergunta em `learning_queries`;
- as evidências utilizadas em `learning_query_evidence`;
- as relações sugeridas em `learning_candidate_relations`, com estado
  `pending_review`.

Nenhuma relação candidata é promovida automaticamente a regra confirmada.

Se a base aprovada não sustentar a resposta, o backend pode usar Google Search
Grounding (`SAFE_CCO_WEB_GROUNDING=1`) e registra a proposta em
`rule_candidates`, no mesmo `portalcco.db`. Somente Administrador ou Supervisor pode aprovar ou rejeitar a
proposta, sempre com fonte, autoridade e justificativa registradas.

## Armazenamento

`SAFE_PORTAL_DB_PATH` define o arquivo SQLite central. Por padrão ele fica em
`data/portalcco.db`. Na primeira inicialização, o backend importa os bancos
legados separados e o antigo `query_graph.json`. A migração é idempotente e
mantém os arquivos de origem sem alterações para recuperação.
