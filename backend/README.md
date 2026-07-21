# Backend RAG

Serviço local que combina recuperação no grafo SAFE com interpretação pelo Gemini.

## Executar

Configure `GEMINI_API_KEY` nas variáveis de ambiente e execute, a partir de `PortalCCO`:

```powershell
python backend/server.py
```

O serviço ficará disponível em `http://127.0.0.1:8765`. O portal tenta essa API primeiro e mantém a busca textual como fallback.

Cada resposta registra no arquivo interno `Knowledge/query_graph.json`:

- a pergunta como nó;
- arestas `answered_using` para as evidências usadas;
- relações sugeridas pelo modelo com estado `pending_review`.

Nenhuma relação candidata é promovida automaticamente a regra confirmada.
