# SAFE Central CCO

Interface web da central operacional de consulta do CCO da SAFE.

## Executar com IA

Com `GEMINI_API_KEY` configurada, execute:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_portal.ps1
```

O navegador abrirá `http://127.0.0.1:8765/`. Mantenha a janela do servidor aberta durante o uso.

## Publicar a aplicação completa

O arquivo `render.yaml` prepara um Web Service Python no Render com:

- publicação automática a partir da branch conectada no GitHub;
- HTTPS no endereço `onrender.com`;
- verificação de saúde em `/api/health`;
- disco persistente de 1 GB montado em `/var/data`;
- cookies de sessão marcados como `Secure`.

No Render, crie um **Blueprint**, conecte este repositório e confirme o plano
`starter`. O disco persistente não está disponível no plano gratuito. A chave
`GEMINI_API_KEY` é opcional e deve ser cadastrada no painel, nunca no Git.

Todos os bancos operacionais são criados automaticamente em `/var/data`. No
primeiro acesso, o portal solicitará o cadastro do administrador inicial.

O GitHub Pages pode continuar existindo como demonstração estática, mas o
endereço oficial dos operadores deve ser o Web Service, pois ele executa login,
permissões e APIs.

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
