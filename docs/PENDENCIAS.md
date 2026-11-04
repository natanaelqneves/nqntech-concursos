# O que só você pode fazer

Tudo o resto fica pronto e testado no GitHub Actions (aba **Actions** do repositório). Faltam só as suas contas e
senhas: elas nunca devem passar por conversa nem ficar no código (o repositório é **público**).
Faça na ordem e marque `[x]` quando terminar. Cada fase acrescenta itens aqui.

---

## Fase 0 — Repositório e base

- [x] Criar o repositório público `natanaelqneves/nqntech-concursos` e liberar o acesso do Claude.
- [x] Escolher a licença: MIT (código) + CC BY 4.0 (textos do site).

### 1. Banco de dados no Neon (gratuito, projeto NOVO) — ~5 min

O Radar TI continua no projeto dele; este é outro projeto, separado.

- [x] Em <https://console.neon.tech>, **New Project**:
  - **Project name:** `nqntech-concursos`
  - **Postgres version:** 17
  - **Region:** *AWS South America (São Paulo)*
- [x] Clique em **Connect**, deixe **Connection pooling desligado** e copie a *connection string*:
      `postgresql://neondb_owner:SENHA@ep-xxxx.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require`
      Ela é o secret `NEON_ADMIN_URL` do passo 2.
- [x] Gere **duas** senhas aleatórias para os usuários das aplicações. No **SQL Editor** do Neon, rode duas vezes
      (ou use seu gerenciador de senhas, 32+ caracteres):
      ```sql
      SELECT replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '');
      ```
      A primeira será `COLETOR_DB_PASSWORD` e a segunda `SITE_DB_PASSWORD`.

### 2. Secrets no GitHub — ~3 min

No repositório: **Settings → Secrets and variables → Actions → New repository secret**. Um por um, nome
exatamente igual, valor sem aspas:

| Nome | Valor |
|---|---|
| `NEON_ADMIN_URL` | a connection string do passo 1 |
| `COLETOR_DB_PASSWORD` | a 1ª senha do passo 1 |
| `SITE_DB_PASSWORD` | a 2ª senha do passo 1 |
| `COLETOR_CONTATO_EMAIL` | e-mail de contato publicado no User-Agent do coletor (os sites sabem quem acessa) |

Secrets de repositório **não** ficam visíveis para quem abre PR de fork: o código público não expõe os valores.

### 3. Criar as tabelas no Neon — 1 clique

- [x] **Actions → migrar → Run workflow**.
- Esperado: verde em ~1 minuto; no passo "Sincronizar senhas" aparece `tabelas no schema concursos: 9`.

### 4. Primeira coleta real — 1 clique

- [x] **Actions → diario → Run workflow** (pode deixar o limite vazio).
- Esperado: `coletar` verde. A primeira execução lê no máximo 60 editais; o acúmulo é drenado nos dias seguintes.
- Depois disso roda sozinho todo dia às **06h17** (Brasília).

### 5. Configurações recomendadas do repositório (opcional) — ~2 min

- [x] **Settings → Code security**: ative *Secret scanning* e *Push protection* (grátis em repositório público).
      A CI também roda o gitleaks a cada push.
- [x] Proteger a `main` (o Claude trabalha por PR): **Settings → Rules → Rulesets → New ruleset → New branch
      ruleset**:
  - **Ruleset name:** `main` · **Enforcement status:** **Active** · **Bypass list:** vazia.
  - **Target branches → Add target → Include default branch**.
  - Marque **Restrict deletions** e **Block force pushes**.
  - Marque **Require a pull request before merging** → *Required approvals*: **0** (projeto de uma pessoa só;
    você não consegue aprovar o próprio PR).
  - Marque **Require status checks to pass** → **Add checks** → digite `banco-e-coletor` e selecione o da
    *GitHub Actions*. Deixe *Require branches to be up to date* desmarcado.
  - **Create**.
- [x] **Settings → General → Pull Requests**: deixe só **Allow squash merging** e marque
      **Automatically delete head branches**.

---

## Fase 1 — Banco ampliado

- [x] Nada a criar. Ao entrar na `main`, o workflow **migrar** roda sozinho (mudou `db/migrations`). Confira em
      **Actions → migrar**: verde e, no passo "Sincronizar senhas", `tabelas no schema concursos: 17`.
      Se ele não tiver rodado, use **Run workflow**.
- [x] No Projeto do Claude, remova os arquivos de **Conhecimento** (`CONTEXTO_PROJETO.md`, `GUIA_PROMPTS.md`) e
      apague as **Instruções do projeto**: tudo agora está em `CLAUDE.md` e `docs/`. Em cada conversa nova, comece
      pela **abertura** do `docs/GUIA_PROMPTS.md`.
- Os concursos já coletados continuam no banco com `publicado = false`: eles só vão para o site quando as fases
  2 a 4 preencherem área, local, slug e resumo. É esperado.

## Fase 2 — Coletor FGV completo

- [ ] Nada a criar. Depois do merge do PR, o workflow **migrar** roda sozinho (nova migration V10). Confira em
      **Actions → migrar**: verde. A coleta diária seguinte já classifica tudo (etapa "classificar").
- Para conferir a classificação com dados reais sem mexer no Neon: **Actions → ensaio → Run workflow**; o resumo
  da execução lista abrangências, áreas, o CNU e os cargos que ficaram em `OUTRAS`.

## Fase 3 — Isenções

- [ ] Nada a criar. Depois do merge, o **migrar** roda sozinho (V11: textos das isenções e reprocessamento dos
      editais já lidos). A coleta diária seguinte grava isenções, prazo, calendário e disciplinas.

## Preparação da Fase 5 — Cloudflare (pode fazer já) — ~5 min

O deploy é feito **só pelo GitHub Actions**. **Não conecte o repositório à Cloudflare** (Workers Builds / "Connect
to Git"): ela não tem acesso ao banco e rodaria um build a cada push. Se o app "Cloudflare Workers and Pages" foi
instalado no GitHub durante o cadastro, remova-o em GitHub → **Settings → Applications** (ou deixe sem nenhum
repositório).

- [x] Criar a conta na Cloudflare (plano grátis).
- [x] **Account ID** (não é o e-mail; é um código de 32 caracteres): painel → **Workers & Pages** → lado direito,
      campo *Account ID* (botão de copiar). Também aparece na URL: `dash.cloudflare.com/<account_id>/...`.
- [x] **API Token**: ícone do perfil → **My Profile → API Tokens → Create Token** → modelo
      **Edit Cloudflare Workers** → *Use template*:
  - **Account Resources:** *Include* → a sua conta (não "All accounts").
  - **Zone Resources:** *All zones from an account* → a sua conta (restrinja ao domínio depois que ele existir).
  - **TTL:** data de fim em 1 ano (anote para renovar).
  - **Continue to summary → Create Token** e copie o valor (só aparece uma vez).
- [x] Secrets no GitHub (**Settings → Secrets and variables → Actions**):

| Nome | Valor |
|---|---|
| `CLOUDFLARE_API_TOKEN` | o token criado acima |
| `CLOUDFLARE_ACCOUNT_ID` | o Account ID |

Nenhum dos dois vai para o `wrangler.jsonc` nem para o código (repositório público).

## Fase 5 — Site no ar

- [x] **Domínio próprio** `ntconcursos.com.br`, ligado como Custom Domain do Worker no painel da Cloudflare.
      O workflow **site** usa esse domínio nas URLs canônicas, no `og:url` e no sitemap (a variável `SITE_URL`
      do repositório, se existir, tem prioridade). O `*.workers.dev` fica desligado no `wrangler.jsonc`, para
      o mesmo conteúdo não aparecer em dois endereços.
- [ ] **E-mail de contato:** Cloudflare → `ntconcursos.com.br` → **Email → Email Routing** → ativar e criar a
      regra `contato@ntconcursos.com.br` → seu Gmail (confirme o e-mail de verificação). É o endereço que aparece
      nas páginas Contato e Privacidade.
- [ ] **Google Search Console:** adicionar a propriedade de domínio `ntconcursos.com.br` (verificação por DNS
      TXT na Cloudflare) e enviar `https://ntconcursos.com.br/sitemap.xml`.

## Anúncios (AdSense) — ~5 min, no painel do AdSense

- [ ] **Mensagem de consentimento (CMP do Google):** AdSense → **Privacidade e mensagens** → **Consentimento**
      (LGPD/"Regulamentações dos EUA e outras") → criar a mensagem para o site e **publicar**. Ela aparece sozinha
      pelo script que já está nas páginas; não precisa de código.
- [ ] **Anúncios automáticos:** AdSense → **Anúncios → Por site** → ligar "Anúncios automáticos" para o domínio.
- [x] O `ads.txt` está na raiz do site e `ntconcursos.com.br` foi enviado para análise em **Sites** (04/11/2026).
      Durante a análise, não tire o script do AdSense do `<head>` nem bloqueie o site.

## Extração com IA (Camada 2) — ~10 min

Sem estas chaves, o coletor continua só com as regras (nada quebra).

- [ ] **Gemini:** entre em https://aistudio.google.com com sua conta Google → **Get API key → Create API key**.
      Copie a chave.
- [ ] **Groq (reserva):** entre em https://console.groq.com → **API Keys → Create API Key**. Copie a chave.
- [ ] GitHub → **Settings → Secrets and variables → Actions → New repository secret**:
  - `GEMINI_API_KEY` = chave do Gemini
  - `GROQ_API_KEY` = chave do Groq
  - `OPENROUTER_API_KEY` = chave do OpenRouter (opcional, 3ª reserva; usa o roteador gratuito `openrouter/free`)
- [ ] (Opcional) aba **Variables**: `COLETOR_IA_MAX_CHAMADAS` (padrão 30 por dia).
- Uma chave de cada provedor só. Criar várias chaves para somar cotas viola os termos de uso.
- Na faixa gratuita do Gemini, o Google pode usar o conteúdo enviado para melhorar os modelos. Aqui só vão trechos
  de editais públicos, sem dado pessoal.

## Fase 6 — Diários oficiais — ~5 min

1. **INLABS (DOU):** crie uma conta gratuita em https://inlabs.in.gov.br e cadastre os secrets `INLABS_EMAIL` e
   `INLABS_SENHA` no repositório (Settings → Secrets and variables → Actions). Sem isso o DOU não entra.
2. **AOCP e IDECAN (opcional):** envie o e-mail (AOCP: candidato@institutoaocp.org.br; IDECAN: formulário Fale Conosco do site) pedindo liberação do User-Agent `NqnTechConcursos/0.1` (rascunho
   na conversa). Se liberarem, a AOCP volta com um `UPDATE fonte SET ativa = true` depois de nova sondagem.

## Importar PDFs manualmente (bancas sem coleta automática)

Passo a passo em `scripts/importar/LEIA-ME.md`: `.env` na raiz com host do Neon e senha do `coletor_app`, depois
`scripts\importar\importar_pdfs.bat PASTA SIGLA [LINK]`.

## Fluxo único: e-mail de pendências (secrets de antes, nada novo) — 2 min

- Os secrets `SMTP_USUARIO`, `SMTP_SENHA` (senha de app do Gmail) e `BUSCA_EMAIL_DESTINO` continuam os mesmos; se
  ainda não existem: na conta Google que envia, ative a verificação em duas etapas, crie a senha de app em
  https://myaccount.google.com/apppasswords e cadastre os três secrets. Sem eles a lista sai só no log do `diario`.
- O workflow `buscar` foi removido: a busca agora roda dentro do `diario` e grava os concursos no banco.
- [ ] Depois do merge: **Actions → migrar** roda sozinho (V19). Confira verde.
- [ ] **Actions → diario → Run workflow** para a primeira busca. No resumo da execução: `DESCOBERTA` da fonte
      `busca-ia`, `LOCALIZACAO` e `PENDENCIAS`. Depois roda sozinho 4x/dia (06:17, 11:17, 16:17 e 21:17).
- Rotina diária: abra o e-mail "aguardando edital", baixe cada PDF no navegador e solte na pasta do Drive com o
  código no nome (`NQ-123 edital.pdf`), na raiz da pasta ou em qualquer subpasta.
- Opcional (variáveis do repositório): `COLETOR_BUSCA_INTERVALO_H` (padrão 11 h por alvo) e `COLETOR_BUSCA_MODELOS`.

## PDFs pelo Google Drive (o GitHub faz o resto) — ~10 min, uma vez

1. https://console.cloud.google.com → crie um projeto (ex.: `nqntech-concursos`) → APIs e serviços → Biblioteca →
   ative a **Google Drive API**.
2. IAM e administrador → Contas de serviço → Criar (ex.: `coletor-drive`), sem papéis. Na conta criada:
   Chaves → Adicionar chave → JSON. Baixa um arquivo `.json` (é uma senha: não envie a ninguém nem ao repositório).
3. No Drive, crie a pasta `NqnTech - editais` e, dentro, uma subpasta por banca com a sigla: `FCC`, `VUNESP`,
   `CESGRANRIO`, `IBFC`, `IDECAN`, `AOCP`... ou `OUTRA`. Compartilhe a pasta principal com o e-mail da conta de
   serviço (termina em `iam.gserviceaccount.com`) como **Editor**.
4. Secrets do repositório: `GOOGLE_SA_JSON` = conteúdo inteiro do `.json`; `DRIVE_PASTA_ENTRADA` = o ID da pasta
   principal (o trecho depois de `/folders/` no endereço dela).
5. Uso: edital de concurso do e-mail de pendências → nome com o código (`NQ-123 edital.pdf`), em qualquer lugar da
   pasta. Concurso novo → subpasta da banca, com o link oficial opcional na **descrição** do arquivo (botão direito →
   Informações do arquivo → Detalhes → Descrição). O `diario` (4x/dia, ou Actions → diario → Run workflow) importa,
   aplica as mesmas regras e move cada PDF para `processados/` ou `recusados/`.

## Próximas fases (só para você se planejar)

- **Fase 7 (alertas):** conta no serviço de e-mail transacional escolhido e hospedagem da API.

## Trocar uma senha

- Usuários do banco: gere nova senha, atualize o secret e rode **Actions → migrar** (ele sincroniza as senhas).
- Administrador do Neon: Neon → Roles → `neondb_owner` → Reset password e atualize `NEON_ADMIN_URL`.
