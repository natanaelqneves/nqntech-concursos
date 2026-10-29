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
- [ ] **Settings → Branches → Add rule** para `main`: exigir o check `ci / banco-e-coletor` antes de merge.

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

## Preparação da Fase 5 — Cloudflare (pode fazer já) — ~5 min

O deploy é feito **só pelo GitHub Actions**. **Não conecte o repositório à Cloudflare** (Workers Builds / "Connect
to Git"): ela não tem acesso ao banco e rodaria um build a cada push. Se o app "Cloudflare Workers and Pages" foi
instalado no GitHub durante o cadastro, remova-o em GitHub → **Settings → Applications** (ou deixe sem nenhum
repositório).

- [x] Criar a conta na Cloudflare (plano grátis).
- [ ] **Account ID** (não é o e-mail; é um código de 32 caracteres): painel → **Workers & Pages** → lado direito,
      campo *Account ID* (botão de copiar). Também aparece na URL: `dash.cloudflare.com/<account_id>/...`.
- [ ] **API Token**: ícone do perfil → **My Profile → API Tokens → Create Token** → modelo
      **Edit Cloudflare Workers** → *Use template*:
  - **Account Resources:** *Include* → a sua conta (não "All accounts").
  - **Zone Resources:** *All zones from an account* → a sua conta (restrinja ao domínio depois que ele existir).
  - **TTL:** data de fim em 1 ano (anote para renovar).
  - **Continue to summary → Create Token** e copie o valor (só aparece uma vez).
- [ ] Secrets no GitHub (**Settings → Secrets and variables → Actions**):

| Nome | Valor |
|---|---|
| `CLOUDFLARE_API_TOKEN` | o token criado acima |
| `CLOUDFLARE_ACCOUNT_ID` | o Account ID |

Nenhum dos dois vai para o `wrangler.jsonc` nem para o código (repositório público).

## Próximas fases (só para você se planejar)

- **Fase 5 (site):** se quiser o domínio próprio, registre (Registro.br para `.com.br`), adicione-o na
  Cloudflare (**Add a domain**, plano Free) e troque os servidores DNS no registrador pelos que a Cloudflare
  indicar. O vínculo do domínio com o site fica no código da fase 5.
- **Fase 7 (alertas):** conta no serviço de e-mail transacional escolhido e hospedagem da API.

## Trocar uma senha

- Usuários do banco: gere nova senha, atualize o secret e rode **Actions → migrar** (ele sincroniza as senhas).
- Administrador do Neon: Neon → Roles → `neondb_owner` → Reset password e atualize `NEON_ADMIN_URL`.
