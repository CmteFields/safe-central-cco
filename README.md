# SAFE Central CCO

Interface web da central operacional de consulta do CCO da SAFE. Abra `index.html` para executar a versão local em modo demonstrativo.

## Conteúdo público

Este repositório contém a interface e o adaptador de integração. A base documental interna e o índice gerado não fazem parte do repositório público.

Sem o índice interno, a interface usa um pequeno catálogo demonstrativo incluído em `app.js`.

## Integração interna

O arquivo `data/knowledge-index.js` é gerado automaticamente a partir do grafo e das regras confirmadas:

```powershell
python PortalCCO/scripts/build_search_index.py
```

Esse comando deve ser executado dentro da estrutura completa de conhecimento da SAFE. O arquivo resultante é ignorado pelo Git para impedir a publicação acidental de metadados documentais internos.

Consulte `docs/ARCHITECTURE.md` antes de adicionar módulos ou novas fontes de dados.
