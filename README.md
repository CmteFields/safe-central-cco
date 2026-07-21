# SAFE Central CCO

Interface web da central operacional de consulta do CCO da SAFE. Abra `index.html` para executar a versão local em modo demonstrativo.

## Conteúdo público

Este repositório contém a interface, o adaptador de integração e um índice público limitado às regras confirmadas. A base documental interna e o índice documental completo não fazem parte do repositório público.

Sem o índice interno, a interface consulta `data/public-knowledge-index.js`, que não contém caminhos internos nem documentos completos.

## Integração interna

O arquivo `data/knowledge-index.js` é gerado automaticamente a partir do grafo e das regras confirmadas:

```powershell
python PortalCCO/scripts/build_search_index.py
```

Esse comando deve ser executado dentro da estrutura completa de conhecimento da SAFE. O arquivo resultante é ignorado pelo Git para impedir a publicação acidental de metadados documentais internos.

Consulte `docs/ARCHITECTURE.md` antes de adicionar módulos ou novas fontes de dados.
