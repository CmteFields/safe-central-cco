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

Na operação com IA, o portal envia a pergunta ao backend. O backend recupera evidências do grafo SAFE e usa `gemini-3.5-flash` para interpretá-las. Somente quando a evidência confirmada for insuficiente, usa `gemini-3.1-pro-preview` com Google Search para procurar páginas oficiais da ANAC. Citações que não sejam reconhecidas como ANAC são descartadas. Toda resposta externa é provisória, entra em `rule_candidates` como não revisada e nunca altera automaticamente o grafo ou as regras aprovadas. Os modelos são configuráveis por `GEMINI_LOCAL_MODEL` e `GEMINI_EXTERNAL_MODEL`.

Falhas transitórias do Gemini são repetidas. Se o Flash permanecer indisponível, o Pro interpreta as mesmas evidências locais sem pesquisa externa. Se ambos falharem, claims confirmados podem fornecer `operator_answer` curado para contingência determinística. Na falta desse texto, as regras confirmadas localizadas ainda são exibidas sem interpretação. Indisponibilidade do modelo não transforma conhecimento confirmado em pergunta não revisada.

Um claim recuperado com `operator_answer` responde antes de qualquer chamada ao Gemini. O mesmo campo é consumido pelo fallback do navegador; portanto, uma indisponibilidade de `/api/ask` não rebaixa a resposta canônica para uma lista lexical. Em perguntas sobre validade operacional do CMA, regras de matrícula não recebem prioridade sobre o claim geral aplicável ao exercício das prerrogativas.

Quando o PythonAnywhere usa um pacote privado mais antigo, `operatorAnswer` do índice público versionado complementa o claim privado pelo mesmo ID. Essa sobreposição altera somente a apresentação canônica, não o status, a fonte ou o conteúdo normativo do claim. `/api/health` informa a versão carregada e o modo da base sem expor caminhos ou segredos.

## Feedback de progresso da consulta

Ao iniciar uma busca, `app.js` exibe um painel acessível com as etapas de recebimento, consulta à base, análise de evidências e preparação da resposta. Como `/api/ask` ainda responde em uma única requisição HTTP, essas etapas representam feedback visual baseado no tempo decorrido, e não eventos transmitidos pelo backend.

Se a requisição falhar, a interface muda para o estado real `fallback`, informa que está consultando o índice local e somente depois apresenta a resposta disponível no dispositivo. O formulário permanece com `aria-busy` durante o processo e impede consultas simultâneas.

## Limites das camadas

- Documentos-fonte não contêm estado transitório da operação.
- `Knowledge` não contém código ou preferências da interface.
- `graphify-out` é sempre regenerável e não deve ser editado manualmente.
- `PortalCCO/data` é sempre regenerável e não é fonte oficial.
- Dados mutáveis não são simulados como documentos Markdown. Usuários, bases, instrutores, aeronaves, passagens, reports, pesquisas, regras em aprovação, auditoria e aprendizagem ficam em tabelas do banco único `portalcco.db`.
- `Regras/catalogo_regras.json` espelha a governança documental na tabela `rule_candidates`. A importação é idempotente e deixa de gerenciar automaticamente um item depois de uma decisão humana registrada no Portal.
- Em implantação pública, o catálogo interno fica no armazenamento persistente indicado por `SAFE_RULES_CATALOG_PATH`; seu conteúdo não é versionado no repositório público.
- Instrutores e aeronaves selecionam suas bases a partir da tabela `bases`, exposta por `/api/bases`; códigos de base livres não são aceitos.
- Passagens entre T1, T2 e T3 são registradas em `handovers`, com prioridade, situação, autoria e trilha temporal, por meio da API `/api/handovers`.
- Pesquisas concluídas são armazenadas como snapshots imutáveis em `search_history`. A API `/api/searches` lista e reabre respostas anteriores sem executar novamente o mecanismo de consulta.
- A autenticação usa as tabelas `users`, `sessions` e `admin_edit_grants`, senhas PBKDF2-SHA256, sessões de 12 horas em cookie `HttpOnly`/`SameSite=Strict` e proteção CSRF. Autorizações são aplicadas no backend para Administrador, Supervisor, Operador e Consulta.
- Em produção, `SAFE_PORTAL_DB_PATH` aponta o banco SQLite para o volume persistente. O Blueprint do Render usa `/var/data/portalcco.db`, HTTPS, cookie `Secure` e uma única instância, preservando a consistência do SQLite.
- Os bancos SQLite antigos são importados automaticamente para o banco único. A tabela `storage_migrations` torna o processo idempotente, e os arquivos legados permanecem intactos como backup.
- Respostas conclusivas devem priorizar regras com estado `confirmed`. Documentos relacionados podem auxiliar a busca, mas não devem ser apresentados como regra confirmada.
- A ordem da resposta é: regra SAFE confirmada e vigente; demais evidências locais rastreáveis; fonte externa oficial da ANAC; ausência de resposta. A consulta externa não substitui uma regra SAFE mais restritiva e não possui validade interna até revisão humana.
- Perguntas e relações inferidas ficam no grafo de aprendizagem. Relações inferidas usam `pending_review` e nunca entram automaticamente no conjunto de regras oficiais.

## Evolução prevista

Quando houver múltiplos operadores e dados em tempo real, a interface continuará em `PortalCCO`, mas o índice estático será substituído por uma API. O contrato deve preservar: texto da resposta, fonte, localização, vigência, confiança e relações utilizadas.
