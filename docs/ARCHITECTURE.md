# Arquitetura da Central CCO SAFE

## Decisão estrutural

A estrutura existente será evoluída sem mover as coleções documentais, pois seus caminhos já são identificadores estáveis usados pelo registro, pelo grafo e pelas decisões curadas.

```text
CentrodeConhecimento/
├── Aeronaves/              # fontes oficiais e institucionais da frota
├── AVOPs/                  # fontes documentais por público
├── Instrutores/            # futura fonte de dados de instrutores
├── MGOP/                   # manual oficial
├── MIP/                    # manual oficial
├── Programas_Instrucao/    # programas oficiais
├── Regras/                 # propostas e regras gerais aprovadas
├── Knowledge/              # curadoria, decisões, registro e validação
├── graphify-out/           # artefatos gerados do grafo
└── PortalCCO/              # aplicação para os operadores
    ├── data/               # índices gerados; não editar manualmente
    ├── docs/               # decisões arquiteturais
    ├── scripts/            # adaptadores entre conhecimento e aplicação
    ├── index.html
    ├── styles.css
    └── app.js
```

## Fluxo de dados

1. Documentos entram nas coleções de origem.
2. `Knowledge` inventaria, deduplica e separa candidatos de regras confirmadas.
3. `graphify-out` materializa nós, relações e versões.
4. `PortalCCO/scripts/build_search_index.py` publica somente o índice necessário à interface.
5. O navegador consulta o índice local sem acessar diretamente arquivos de curadoria ou documentos sensíveis.

Na operação com IA, o portal envia a pergunta ao backend local. O backend recupera evidências, solicita ao Gemini uma resposta estruturada, devolve somente fontes utilizadas e registra a travessia em `Knowledge/query_graph.json`.

## Limites das camadas

- Documentos-fonte não contêm estado transitório da operação.
- `Knowledge` não contém código ou preferências da interface.
- `graphify-out` é sempre regenerável e não deve ser editado manualmente.
- `PortalCCO/data` é sempre regenerável e não é fonte oficial.
- Dados mutáveis de instrutores, manutenção e restrições exigirão repositório operacional próprio ou API; não devem ser simulados como documentos Markdown.
- Respostas conclusivas devem priorizar regras com estado `confirmed`. Documentos relacionados podem auxiliar a busca, mas não devem ser apresentados como regra confirmada.
- Perguntas e relações inferidas ficam no grafo de aprendizagem. Relações inferidas usam `pending_review` e nunca entram automaticamente no conjunto de regras oficiais.

## Evolução prevista

Quando houver múltiplos operadores e dados em tempo real, a interface continuará em `PortalCCO`, mas o índice estático será substituído por uma API. O contrato deve preservar: texto da resposta, fonte, localização, vigência, confiança e relações utilizadas.
