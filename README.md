# CCO - Central de conhecimento

Interface web da central operacional de consulta do CCO da SAFE.

## Executar com IA

Com `GEMINI_API_KEY` configurada, execute:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_portal.ps1
```

O navegador abrirá `http://127.0.0.1:8765/`. Mantenha a janela do servidor aberta durante o uso.

O portal consulta primeiro as regras aprovadas. Quando a evidência local é
insuficiente, `SAFE_CCO_WEB_GROUNDING=1` (padrão) permite ao Gemini pesquisar
fontes oficiais na web. A resposta externa é sempre marcada como provisória e
registrada em **Gestão de regras > Em aprovação**; ela nunca é promovida
automaticamente. Defina `SAFE_CCO_WEB_GROUNDING=0` para desativar esse fallback.

## Publicar a aplicação completa

### PythonAnywhere (sem cartão)

O portal também pode ser publicado em uma conta gratuita do PythonAnywhere. A
entrada WSGI está em `backend/wsgi.py` e a configuração pronta para a conta
`CCOFields` está em `pythonanywhere_wsgi.py.example`.

1. Em um console Bash do PythonAnywhere, clone o repositório e crie a pasta
   persistente:

   ```bash
   git clone https://github.com/CmteFields/safe-central-cco.git
   mkdir -p /home/CCOFields/portalcco-data
   ```

2. Pela aba **Files**, crie o arquivo privado
   `/home/CCOFields/.portalcco-secrets.json`:

   ```json
   {
     "SAFE_CCO_SETUP_TOKEN": "substitua-por-um-codigo-forte-e-exclusivo",
     "GEMINI_API_KEY": ""
   }
   ```

   O primeiro valor será solicitado apenas no cadastro do administrador
   inicial. A chave Gemini é opcional. Esse arquivo fica fora do repositório e
   não deve ser enviado ao GitHub.

3. Na aba **Web**, escolha **Add a new web app**, selecione **Manual
   configuration** e a versão de Python disponível mais recente.

4. Abra o arquivo de configuração WSGI indicado na aba **Web** e substitua seu
   conteúdo pelo conteúdo de `pythonanywhere_wsgi.py.example`.

5. Pressione **Reload**. O portal ficará disponível em
   `https://ccofields.pythonanywhere.com`.

Os bancos de usuários, instrutores, aeronaves, bases, passagens, reports, pesquisas e regras em aprovação
ficam em `/home/CCOFields/portalcco-data`, fora do GitHub e preservados entre
recargas da aplicação.

### Render

O arquivo `render.yaml` prepara um Web Service Python no Render com:

- publicação automática a partir da branch conectada no GitHub;
- HTTPS no endereço `onrender.com`;
- verificação de saúde em `/api/health`;
- disco persistente de 1 GB montado em `/var/data`;
- cookies de sessão marcados como `Secure`.

No Render, crie um **Blueprint**, conecte este repositório e confirme o plano
`starter`. O disco persistente não está disponível no plano gratuito. A chave
`GEMINI_API_KEY` é opcional e deve ser cadastrada no painel, nunca no Git.
Durante a criação, informe um valor forte e exclusivo para
`SAFE_CCO_SETUP_TOKEN`; esse código será exigido somente no cadastro do primeiro
administrador e ficará armazenado como segredo no Render.

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
