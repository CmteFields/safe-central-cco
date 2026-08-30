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

Na operação com IA, o portal envia a pergunta ao backend. O backend recupera evidências do grafo SAFE e usa `gemini-3.6-flash` para interpretá-las, com `gemini-3.5-flash-lite` como contingência de capacidade. Erros transitórios usam repetição exponencial com jitter antes da troca de modelo. Somente quando a evidência confirmada for insuficiente, usa `gemini-3.1-pro-preview` com Google Search para procurar páginas oficiais da ANAC. Se o Pro estiver sem cota ou indisponível, a mesma pesquisa oficial é repetida com `gemini-3.6-flash` e depois com Flash-Lite, modelos igualmente compatíveis com Google Search. Citações que não sejam reconhecidas como ANAC são descartadas. Toda resposta externa é provisória, entra em `rule_candidates` como não revisada e nunca altera automaticamente o grafo ou as regras aprovadas. Os modelos são configuráveis por `GEMINI_LOCAL_MODEL`, `GEMINI_FALLBACK_MODEL` e `GEMINI_EXTERNAL_MODEL`.

Falhas transitórias do Gemini são repetidas. Se o modelo principal permanecer indisponível, o Flash-Lite interpreta as mesmas evidências locais sem pesquisa externa. Se ambos falharem, claims confirmados podem fornecer `operator_answer` curado para contingência determinística. Na falta desse texto canônico, resultados lexicais são identificados somente como evidências relacionadas e a consulta é declarada inconclusiva; eles nunca recebem apresentação de resposta confirmada. Indisponibilidade do modelo não transforma conhecimento confirmado em pergunta não revisada.

Um claim recuperado com `operator_answer` responde antes de qualquer chamada ao Gemini. O mesmo campo é consumido pelo fallback do navegador; portanto, uma indisponibilidade de `/api/ask` não rebaixa a resposta canônica para uma lista lexical. Em perguntas sobre validade operacional do CMA, regras de matrícula não recebem prioridade sobre o claim geral aplicável ao exercício das prerrogativas.

A recuperação pesquisa título, escopo e conteúdo integral de `operator_answer`. Códigos operacionais citados em conjunto, como `NAV02` e `NAV03`, recebem prioridade quando aparecem na mesma regra. Se a etapa determinística não localizar resposta canônica, o modelo local primeiro converte a linguagem natural em termos equivalentes de busca, reduz o catálogo por esses termos e então executa a seleção semântica somente sobre os IDs confirmados mais pertinentes. Apenas depois as evidências escolhidas são usadas para responder. As duas etapas não criam regras e a saída final é validada contra IDs existentes.

Quando o PythonAnywhere usa um pacote privado mais antigo, `operatorAnswer` do índice público versionado complementa o claim privado pelo mesmo ID. Essa sobreposição altera somente a apresentação canônica, não o status, a fonte ou o conteúdo normativo do claim. A operação completa exige o pacote privado instalado e `/api/health` com `knowledge` igual a `private_bundle` ou `configured_root`; `public_index` é apenas contingência resumida. O endpoint informa se a Gemini está configurada e os nomes dos modelos ativos, sem expor a chave, os caminhos ou outros segredos. Falhas reais das chamadas são devolvidas somente a Supervisor e Administrador na própria resposta da consulta.

No PythonAnywhere, a publicação automatizada usa exclusivamente a API oficial.
Os arquivos públicos necessários à execução são enviados para uma release
imutável identificada pelo commit do `PortalCCO`; dados operacionais e segredos
permanecem nos diretórios persistentes externos à release. O WSGI só é apontado
para a nova release depois que todos os arquivos foram enviados. Após a recarga,
`/api/health` deve confirmar o `RELEASE_ID`; caso contrário, o WSGI anterior é
restaurado e a aplicação é recarregada novamente. Esse fluxo elimina a
dependência de console ou navegador para implantações rotineiras.

Geração, testes e publicação são separados por um comprovante local de release.
`small-answer` cobre a revisão limitada de uma claim existente;
`knowledge-rule` cobre uma única claim confirmada nova e seus aliases; `full`
cobre código, fontes e mudanças estruturais. A preparação reconstrói Knowledge,
Graphify e o índice público uma vez, executa os testes proporcionais e registra
hashes de todos os arquivos do pacote privado e da release pública. Depois dos
commits e pushes, o deploy recalcula os hashes e é bloqueado se qualquer byte ou
fila tiver mudado. Assim, o conteúdo publicado é exatamente o conteúdo testado,
sem reconstrução ou repetição de suíte após o commit.

## Feedback de progresso da consulta

Ao iniciar uma busca, `app.js` exibe um painel acessível com as etapas de recebimento, consulta à base, análise de evidências e preparação da resposta. Como `/api/ask` ainda responde em uma única requisição HTTP, essas etapas representam feedback visual baseado no tempo decorrido, e não eventos transmitidos pelo backend.

Se a requisição falhar, a interface muda para o estado real `fallback`, informa que está consultando o índice local e somente depois apresenta a resposta disponível no dispositivo. O formulário permanece com `aria-busy` durante o processo e impede consultas simultâneas.

## Limites das camadas

- Documentos-fonte não contêm estado transitório da operação.
- `Knowledge` não contém código ou preferências da interface.
- `graphify-out` é sempre regenerável e não deve ser editado manualmente.
- `PortalCCO/data` é sempre regenerável e não é fonte oficial.
- Dados mutáveis não são simulados como documentos Markdown. Usuários, bases, instrutores, aeronaves, passagens, reports, pesquisas, regras em aprovação, auditoria e aprendizagem ficam em tabelas do banco único `portalcco.db`.
- Reports armazenam responsável, comentários, anexos e eventos de auditoria no banco privado. Indicações de pergunta mantêm vínculo explícito com `rule_candidates`: descarte rejeita a candidata, resolução pode encaminhá-la para aprovação ou encerrá-la como já coberta/sem regra. O perfil Consulta não acessa o módulo; Operadores criam e complementam os próprios registros, enquanto Supervisores e Administradores executam a tratativa.
- `Regras/catalogo_regras.json` espelha a governança documental na tabela `rule_candidates`. A importação é idempotente e deixa de gerenciar automaticamente um item depois de uma decisão humana registrada no Portal.
- Em implantação pública, o catálogo interno fica no armazenamento persistente indicado por `SAFE_RULES_CATALOG_PATH`; seu conteúdo não é versionado no repositório público.
- Instrutores e aeronaves selecionam suas bases a partir da tabela `bases`, exposta por `/api/bases`; códigos de base livres não são aceitos.
- Passagens entre T1, T2 e T3 são registradas em ciclos (`handover_cycles`), itens (`handovers`) e eventos imutáveis de auditoria (`handover_events`), por meio da API `/api/handovers`. O turno operacional atual é determinado no servidor: enquanto houver ciclo em elaboração ou aguardando recebimento, prevalece sua origem; após o recebimento, prevalece o destino confirmado. O relógio de São Paulo é usado apenas como contingência quando ainda não existe histórico. Um ticket novo não recebe origem ou destino do navegador: o servidor o vincula ao turno operacional atual e registra como responsável inicial o usuário autenticado. A passagem, e não cada ticket, define o destino; enquanto estiver em elaboração, seu destino pode seguir a sequência circular (`T1 → T2 → T3 → T1`) ou pular um turno, com a escolha registrada na auditoria. Rascunhos podem ser encerrados sem publicação, preservando itens e eventos no histórico sem avançar o turno operacional. A API identifica um único ciclo ativo, calcula os indicadores do ciclo separadamente e entrega no máximo 25 ciclos anteriores. Também projeta `active_tickets` a partir da ocorrência mais recente de cada `root_item_id`, sem mover nem regravar os registros existentes: pendências permanecem ativas enquanto estiverem pendentes ou em andamento, e informações permanecem ativas até serem explicitamente resolvidas. A interface fixa essa fila operacional acima da passagem atual, independentemente do filtro ou da troca de turno; conclusão ou resolução retira o ticket apenas da fila ativa e preserva integralmente suas ocorrências e eventos no histórico. Cada anotação exige classificação explícita pela base responsável pela execução: `SBSJ` para São José dos Campos, `SDAM` para Campo dos Amarais/Campinas e `Geral` somente quando o assunto afeta as duas bases ou o CCO. Ao reabrir uma pendência histórica, uma nova ocorrência é criada no ciclo em elaboração, preservando intacta a conclusão anterior.
- Pesquisas concluídas são armazenadas como snapshots imutáveis em `search_history`. A API `/api/searches` lista e reabre respostas anteriores sem executar novamente o mecanismo de consulta.
- A autenticação usa as tabelas `users`, `sessions` e `admin_edit_grants`, senhas PBKDF2-SHA256, sessões de 12 horas em cookie `HttpOnly`/`SameSite=Strict` e proteção CSRF. Autorizações são aplicadas no backend para Administrador, Supervisor, Operador e Consulta.
- Em produção, `SAFE_PORTAL_DB_PATH` aponta o banco SQLite para o volume persistente. O Blueprint do Render usa `/var/data/portalcco.db`, HTTPS, cookie `Secure` e uma única instância, preservando a consistência do SQLite.
- Os bancos SQLite antigos são importados automaticamente para o banco único. A tabela `storage_migrations` torna o processo idempotente, e os arquivos legados permanecem intactos como backup.
- Respostas conclusivas devem priorizar regras com estado `confirmed`. Documentos relacionados podem auxiliar a busca, mas não devem ser apresentados como regra confirmada.
- A ordem da resposta é: regra SAFE confirmada e vigente; demais evidências locais rastreáveis; fonte externa oficial da ANAC; ausência de resposta. A consulta externa não substitui uma regra SAFE mais restritiva e não possui validade interna até revisão humana.
- Perguntas e relações inferidas ficam no grafo de aprendizagem. Relações inferidas usam `pending_review` e nunca entram automaticamente no conjunto de regras oficiais.

## Lacunas de conhecimento e retorno ao grafo

Toda consulta sem cobertura conclusiva cria ou atualiza um item em `rule_candidates`. A
contagem aumenta somente quando um usuário repete a pergunta; o botão de reprocessamento
consulta novamente a base e a ANAC sem inflar essa contagem. `/api/knowledge-gaps` entrega
o relatório consolidado, com autoria, datas, recorrência e agrupamentos lexicais apenas
para triagem. Os agrupamentos não fundem registros e não aprovam conhecimento.

Supervisor e Administrador podem exportar o relatório em CSV e imprimir a página em PDF.
Quando uma regra é aprovada, ela passa a responder imediatamente no Portal e o backend
regenera `approved-rules-export.json` no armazenamento privado. O utilitário
`scripts/sync_portal_approved_rules.py` baixa esse pacote para
`Regras/Entradas/portal_regras_aprovadas.json`. Essa entrada continua sem autoridade
documental automática: a publicação no grafo exige consolidar a regra em
`regras_aprovadas.md` e `catalogo_regras.json`, criar ou revisar a claim rastreável e
executar `Knowledge/update_knowledge.py`. Assim, a sincronização é auditável e nenhuma
resposta provisória é promovida sem decisão humana.

## Evolução prevista

Quando houver múltiplos operadores e dados em tempo real, a interface continuará em `PortalCCO`, mas o índice estático será substituído por uma API. O contrato deve preservar: texto da resposta, fonte, localização, vigência, confiança e relações utilizadas.
