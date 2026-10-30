# NqnTech Concursos — Contexto do Projeto

> Documento de referência (fonte da verdade), mantido **só no repositório** (sem cópias no Projeto do Claude).
> Atualizar por commit sempre que uma decisão mudar. As instruções de trabalho do Claude ficam em `CLAUDE.md`.
> Criado em 29/10/2026 a partir da experiência do **Radar TI** (repositório `natanaelqneves/radar-ti`), que
> continua existindo, separado, como serviço pessoal.

---

## 1. Objetivo

Site **público e gratuito** de concursos públicos do Brasil, com informação **direta e simples**:

- Concursos **previstos, abertos e encerrados**, de **todas as áreas**, **todos os níveis** e **todos os estados**.
- **Resumo próprio de cada concurso**, gerado automaticamente a partir dos dados do edital (cargos, vagas,
  salários, escolaridade, inscrições, prova, taxa, isenções), sempre com link para o edital oficial.
- **Isenções de taxa** em destaque: o que cada edital prevê e páginas explicativas por tipo de isenção
  (CadÚnico, doadores de sangue/medula, jurados etc.). Objetivo social: **democratizar o acesso a concursos**.
- **Alertas por e-mail**: a pessoa informa **nome e e-mail** e monta o próprio filtro (estados, áreas, níveis,
  "só com isenção"). Nada além disso é pedido.
- **Informação sempre gratuita.** Monetização prevista (doações, afiliados, anúncios) apenas para cobrir custos
  e manter o projeto; regras na seção 10.

O site é **alimentado pelos motores de coleta** (coletores automáticos). Não há cadastro manual de concursos.

### Fora do escopo (por enquanto)
Login com senha, comentários, conteúdo de cursinho, venda de produtos próprios, cobrança pela informação,
aplicativo móvel.

---

## 2. Arquitetura

```
                         GitHub Actions (repositório PÚBLICO, agendado 1x/dia)
 Fontes ──► COLETOR (Python) ──► PostgreSQL (Neon) ──► GERADOR DO SITE (Java/Thymeleaf) ──► HTML estático
 (bancas,    descobrir, vincular,      ▲   │              páginas + sitemap.xml + busca.json       │
  diários)   baixar (temporário),      │   │                                                        ▼
             extrair, classificar,     │   └──► ALERTAS (Java) ──► serviço de e-mail ──► assinantes  site público
             estruturar, resumir       │                                                          (Cloudflare)
                                       │
                      API DE CADASTRO (Spring Boot, fase 7) ◄── formulário do site (nome, e-mail, filtro)
```

**Decisões centrais**
- **Site estático gerado após cada coleta**: os dados mudam no máximo uma vez por dia; só as páginas que
  mudaram são regeradas. HTML pronto dá velocidade, custo baixo, nenhuma superfície de ataque e **ótima
  indexação no Google** (SEO). (Decisão de 29/10/2026: avaliado e descartado site renderizado a cada acesso.)
- **Hospedagem na Cloudflare (Workers com assets estáticos, plano grátis)**: requisições a assets estáticos são
  grátis e ilimitadas, uso comercial permitido (anúncios/afiliados), CDN, domínio próprio e deploy pelo GitHub
  Actions com um token. Limite do plano grátis: **20.000 arquivos por versão** (25 MiB por arquivo); o plano
  pago (US$ 5/mês) sobe para 100.000. Para não estourar, concursos `ENCERRADO` há mais de **180 dias** (mesmo
  prazo da retenção, seção 5) saem das páginas estáticas e do `busca.json` (ficam no banco). Avaliadas em
  29/10/2026: Vercel (Hobby proíbe anúncios; Pro US$ 20/mês) e GitHub Pages (área cinzenta para uso comercial).
- **Deploy só pelo GitHub Actions** (`wrangler deploy` com `CLOUDFLARE_API_TOKEN` e `CLOUDFLARE_ACCOUNT_ID` em
  GitHub Secrets). O repositório **não** é conectado à Cloudflare (sem Workers Builds): o site depende do banco
  e da ordem coleta → geração → deploy, e a Cloudflare recebe só a pasta de HTML pronta, nunca segredos do
  banco nem o código de coleta. O Worker é **só de assets, sem script**: requisições a assets estáticos não
  entram no limite de 100 mil requisições/dia do plano grátis.
- **Coletores e site nunca conversam diretamente**: o banco é o ponto de encontro (mesma regra do Radar TI).
- **Busca/filtros no navegador** sobre um `busca.json` gerado junto com o site (sem servidor). Se o volume
  crescer demais (ex.: histórico de encerrados), a busca passa a um endpoint da API sem mudar a tela.
- **Único componente com servidor**: a API de cadastro de alertas (fase 7). Hospedagem gratuita a escolher
  nessa fase, **conferindo os limites atuais** antes de decidir.
- A coleta roda no GitHub Actions (grátis e sem limite de minutos em repositório **público**). Rodar o coletor
  localmente continua possível (mesmo código), útil para cargas grandes pontuais.

### Ambientes
| Ambiente | Banco | E-mail | Site |
|---|---|---|---|
| CI (a cada push) | Postgres 17 descartável + Flyway | GreenMail/Mailpit | gerado e validado, não publicado |
| Ensaio (manual) | Postgres descartável, dono sem superusuário (igual Neon) | Mailpit | gerado como artefato |
| Produção | Neon (projeto `nqntech-concursos`, separado do Radar TI) | serviço transacional (fase 7) | Cloudflare (Workers static assets) |
| Local (opcional) | Docker | Mailpit | `http://127.0.0.1` |

---

## 3. Stack

| Parte | Escolha | Motivo |
|---|---|---|
| Coletor | Python 3.13 (base copiada do Radar TI) | httpx, BeautifulSoup, pdfplumber já testados |
| Gerador do site | Java 25 + Spring Boot 4.1 (modo linha de comando) + Thymeleaf | Domínio do desenvolvedor; páginas prontas para o Google |
| Front-end | HTML + CSS próprio + JavaScript simples (filtros) | Leve, acessível, funciona em celular fraco |
| API de cadastro | Spring Boot 4.1 (web) + Validation | Fase 7 |
| Alertas | Spring Boot (linha de comando) + Spring Mail + Thymeleaf | Mesmo padrão do notificador do Radar TI |
| Banco | PostgreSQL 17 no Neon, schema `concursos` | Gratuito; 1 GB; dorme quando ocioso |
| Migrations | Flyway 12 | Mesmo esquema em todos os ambientes |
| Hospedagem do site | Cloudflare Workers (assets estáticos) + domínio próprio | Grátis, comercial permitido, CDN; deploy pelo GitHub Actions |
| E-mail dos alertas | Serviço transacional com faixa gratuita (escolher na fase 7) | Gmail não serve para envio a muitas pessoas |
| Painel administrativo | Angular (opcional, fase 9) | Portfólio; não precisa de SEO |

---

## 4. Domínio de dados

### 4.1 Áreas (catálogo fixo, editável por migration)
`ADMINISTRATIVA`, `BANCARIA`, `CONTROLE_FISCAL` (auditoria, fiscal, tributária), `EDUCACAO`, `ENGENHARIA_ARQUITETURA`,
`JURIDICA`, `LEGISLATIVA`, `MEIO_AMBIENTE_AGRARIA`, `POLICIAL_SEGURANCA`, `SAUDE`, `TI`, `ASSISTENCIA_SOCIAL`,
`COMUNICACAO_ARTES`, `OPERACIONAL` (motorista, auxiliar de serviços etc.), `OUTRAS`.

A classificação de cada cargo é feita por **regras de palavras-chave por área** (arquivo `areas.yml`, mesma técnica
do `perfil.yml` do Radar TI: minúsculas, sem acento, palavra inteira, termos de exclusão). Cargo sem área
identificada → `OUTRAS`, com aviso. Um cargo tem uma área principal.

### 4.2 Escolaridade
`FUNDAMENTAL`, `MEDIO`, `TECNICO`, `SUPERIOR`.

### 4.3 Situação do concurso
`PREVISTO` (sem edital), `INSCRICOES_ABERTAS`, `EM_ANDAMENTO` (inscrições encerradas, certame em curso),
`ENCERRADO` (homologado/finalizado ou fora da listagem da banca). Derivada de datas + status da fonte.

### 4.4 Isenções (catálogo + o que cada edital prevê)
Tipos iniciais (`isencao_tipo.codigo`): `CADUNICO`, `DOADOR_MEDULA`, `DOADOR_SANGUE`, `DOADOR_PLASMA`, `JURADO`,
`MESARIO_ELEITORAL`, `PESSOA_COM_DEFICIENCIA`, `VITIMA_VIOLENCIA_DOMESTICA`, `ESTUDANTE`, `DESEMPREGADO`, `OUTRA`.

- **Página explicativa por tipo**: o que é, quem costuma ter direito, documentos usuais, base legal citada nos
  editais (com link oficial), e o aviso: *"as regras variam por edital; confira sempre o edital"*.
- **Por concurso**: tipos previstos no edital, **período para pedir a isenção** e link do edital.
  Exemplo real (TJPB 2026, FGV): CadÚnico, doadores de sangue ou medula, jurados, mulheres vítimas de violência
  doméstica e doadores de plasma, cada um com regras próprias.
- Linguagem **sempre informativa**: "este edital prevê isenção para…", nunca "você tem direito".

### 4.5 Resumo do concurso
Texto curto (3 a 6 frases) **gerado por regras a partir dos campos estruturados**, nunca copiado de notícia ou do
edital. Exemplo:
> "O Tribunal de Justiça da Paraíba (PB) abriu concurso com 50 vagas para nível superior, salário de R$ 7.526,14,
> em áreas jurídica, TI e contabilidade. Inscrições até 18/11/2026, taxa de R$ 120,00. Prova em 24/01/2027.
> O edital prevê isenção da taxa para inscritos no CadÚnico, doadores de sangue ou medula e outros casos.
> Banca: FGV."

Campos ausentes são omitidos do texto (sem inventar). Avisos de extração aparecem como "confira o edital".
Um resumo por LLM pode ser plugado depois (fase opcional), validado contra os campos estruturados.

---

### 4.6 Decisões de produto (29/10/2026, a implementar nas fases 1–5)
- **Tela inicial: só concursos com inscrições abertas** (decisão revista em 29/10/2026). Ordem:
  1. **CNU** (Concurso Nacional Unificado) primeiro;
  2. depois os demais de abrangência **`NACIONAL`**;
  3. depois estaduais e municipais.
  Dentro de cada grupo, por **data da prova**, da mais próxima para a mais distante; sem data de prova vão ao fim
  do grupo (desempate: `inscricao_fim` mais próximo). Concursos com isenção ganham selo com os dias restantes
  para pedir, mas o prazo de isenção **não** define mais a ordem. Previstos e encerrados ficam na busca e nas
  páginas de estado/área (SEO).
- **CNU**: identificado pelo coletor por regra (título ou endereço com "Concurso Nacional Unificado", "CNU",
  "CPNU", em `config/destaques.yml`) e gravado em `concurso.unificado` (V10; sempre `NACIONAL`). O CNU 2 é
  organizado pela FGV e aparece na listagem dela (`/cpnu2`), então já vem pela fonte atual.
- **Navegação geográfica Brasil → regiões → estados → municípios**: tabela de municípios do IBGE (código, nome, UF,
  região) por migration; concurso municipal ligado ao código IBGE. Federais/nacionais = categoria **"Nacional"**,
  exibidos em qualquer recorte; estaduais aparecem no estado e nos municípios dele. Órgão federal de um estado só
  (TRT da 13ª Região, universidade ou instituto federal com o estado no nome) entra como **estadual**, porque as
  vagas são daquele estado (decisão da fase 2). Páginas `/brasil/`,
  `/regiao/<regiao>/`, `/estado/<uf>/`, `/municipio/<uf>/<municipio>/` + filtros encadeados no navegador.
- **Por concurso**: dias restantes para pedir isenção (recalculado no navegador a partir de `isencao_fim`);
  **calendário** (tabela de eventos: evento, início, fim; "a definir" quando o edital não traz data);
  **matérias = só a lista de disciplinas por cargo** (nunca o conteúdo programático); **tem redação/discursiva**
  (booleano por cargo, com aviso "confira o edital" quando incerto). Extração na fase 3, junto com isenções.
- **Espaços de afiliados**: bloco "Prepare-se para este concurso" na página do concurso (após resumo e cargos,
  nunca dentro do resumo), blocos discretos em páginas de área/estado e no rodapé dos alertas; no máximo 1–2 por
  página; rótulo "Publicidade"/"Link de parceiro"; `rel="sponsored nofollow"`; parceiros em `config/parceiros.yml`
  por área/banca. Páginas de isenção mostram só material gratuito. Só links simples (sem scripts de afiliado).
- **Cookies**: o site não cria cookies; filtros podem lembrar escolhas em `localStorage`; estatísticas pelo
  Cloudflare Web Analytics (sem cookies). Banner de consentimento só se entrarem anúncios com cookies.

## 5. Modelo de dados (schema `concursos`)

Base herdada do Radar TI, com acréscimos marcados com ★.

```
-- geografia e catálogos (só migration altera; slug = trecho da URL)
★ regiao         (sigla PK [N|NE|CO|SE|S], nome, slug, ordem)
★ uf             (sigla PK, nome, codigo_ibge, regiao, slug)
★ municipio      (codigo_ibge PK, nome, uf, slug)       UNIQUE (uf, slug); 5.571 do IBGE (V6, gerada pela captura-ibge)
★ area           (codigo PK, nome, slug, ordem)         -- seção 4.1
★ escolaridade   (codigo PK, nome, slug, ordem)         -- seção 4.2
★ isencao_tipo   (codigo PK, nome, slug, ordem, descricao, base_legal, link_oficial)   -- textos na fase 3

banca            (id, nome, sigla, site, coleta_permitida, observacao)
orgao            (id, nome, sigla, esfera[FEDERAL|ESTADUAL|MUNICIPAL], uf→uf, municipio, ★ municipio_ibge)
                                                                                     UNIQUE NULLS NOT DISTINCT
fonte            (id, tipo, nome, banca_id?, ativa, url_base)
sinal_descoberta (id, fonte_id, titulo, url, data_publicacao, payload JSONB, status, concurso_id?,
                  criado_em, visto_em)                                                  UNIQUE (fonte_id, url)
concurso         (id, orgao_id, banca_id, titulo, numero_edital, ano, situacao, inscricao_inicio, inscricao_fim,
                  data_prova, taxa_min, taxa_max, link_oficial, link_inscricao, avisos_extracao JSONB,
                  possivel_duplicado, edital_documento_id?, origem_estrutura, criado_em, atualizado_em,
                ★ slug UNIQUE,            -- URL amigável e estável: tjpb-2026-analista-judiciario
                ★ abrangencia [NACIONAL|ESTADUAL|MUNICIPAL],   -- NACIONAL aparece em qualquer recorte
                ★ uf→uf, municipio_ibge,  -- local principal; FK (uf, municipio_ibge)→municipio garante coerência
                ★ total_vagas, salario_max, escolaridades text[], areas text[],   -- desnormalizado p/ o site
                ★ tem_isencao, isencao_inicio?, isencao_fim?,
                ★ resumo, resumo_gerado_em, publicado,  -- publicar exige slug + abrangencia + resumo
                ★ encerrado_em,           -- marcado por gatilho ao virar ENCERRADO (retenção)
                ★ unificado)              -- CNU: primeiro na tela inicial (seção 4.6; migration na fase 2)
                                                                                     UNIQUE (link_oficial)
cargo            (id, concurso_id, nome, especialidade, escolaridade→escolaridade, vagas, cadastro_reserva,
                  salario, uf_lotacao→uf, ★ area→area, ★ disciplinas text[] (só nomes),
                ★ tem_redacao (NULL = não identificado → "confira o edital"))
documento        (id, concurso_id, tipo, titulo, url_origem UNIQUE, hash_sha256, data_publicacao,
                  texto_extraido, status_extracao, criado_em)
★ concurso_isencao (concurso_id, tipo_codigo→isencao_tipo, observacao)        PK (concurso_id, tipo_codigo)
★ concurso_evento  (id, concurso_id, ordem, evento, inicio?, fim?)  UNIQUE (concurso_id, ordem); nulo = "a definir"
execucao_coleta  (id, fonte_id?, etapa, inicio, fim, status, itens_novos, mensagem_erro)

-- fase 7 (alertas)
★ assinante      (id, nome, email UNIQUE (minúsculo), status[PENDENTE|ATIVO|DESCADASTRADO], criado_em,
                  confirmado_em?, consentimento_em, versao_politica, ultimo_envio_em?)
★ assinante_filtro (assinante_id PK, ufs text[], areas text[], escolaridades text[], somente_com_isencao,
                  frequencia[DIARIA|SEMANAL])
★ token_acesso   (id, assinante_id, finalidade[CONFIRMAR|GERENCIAR|DESCADASTRAR], hash_sha256, expira_em, usado_em?)
★ alerta_envio   (id, assinante_id, enviado_em, status, qtd_concursos, mensagem_erro)
★ alerta_item    (alerta_envio_id, concurso_id)          UNIQUE (assinante, concurso) — nunca repetir
```

**Regras no banco (fase 1):** `areas[]` validado contra o catálogo por gatilho; `escolaridades[]` por CHECK;
o site (`site_app`) só enxerga concursos `publicado` e as linhas filhas deles (RLS), e só lê uma lista branca
de tabelas públicas (testada: tabela nova nasce invisível para o site).

**Retenção (limite de 1 GB):** texto de editais de concursos `ENCERRADO` há mais de 180 dias é apagado (os campos
estruturados e o resumo ficam). Assinantes `PENDENTE` não confirmados em 7 dias são apagados.
Descadastro **apaga** o assinante e o filtro (não só marca).

---

## 6. Pipeline diário

| Etapa | Quem | O que faz |
|---|---|---|
| 1. Descoberta | Coletor | Fontes ativas → `sinal_descoberta` (abertos **e** encerrados recentes) |
| 2. Vinculação/deduplicação | Coletor | Sinal → concurso (chaves do Radar TI: URL → hash → órgão+edital+ano → similaridade) |
| 3. Documentos | Coletor | PDF em pasta temporária → hash + texto → apagado |
| 4. Estruturação | Coletor | Cargos, datas, taxas, **seção de isenções**, calendário, disciplinas e redação por cargo, avisos |
| 5. Classificação | Coletor | Área de cada cargo (`areas.yml`), escolaridade, abrangência/local, CNU (`destaques.yml`), situação por data |
| 6. Resumo | Coletor | Resumo por regras + campos desnormalizados + `slug` |
| 7. Site | Gerador (Java) | Páginas HTML, `busca.json`, `sitemap.xml`, `robots.txt` (só o que mudou) → Cloudflare |
| 8. Alertas | Alertas (Java) | Para cada assinante ativo: concursos novos que batem com o filtro → e-mail |

A coleta inicial é limitada por execução (ex.: 60 editais/dia) e drena o acúmulo em poucos dias.

---

## 7. Site (SEO e acessibilidade)

Páginas:
- `/` — só concursos com inscrições abertas: CNU, depois nacionais, depois os demais; em cada grupo, prova mais
  próxima primeiro (seção 4.6); selo "com isenção" com os dias restantes para pedir.
- `/concursos/` — lista com filtros (UF, área, nível, situação, isenção, salário) no navegador.
- `/concurso/<slug>/` — resumo, tabela de cargos, datas, taxa, isenções, links oficiais, "última atualização".
- `/brasil/`, `/regiao/<regiao>/`, `/estado/<uf>/`, `/municipio/<uf>/<municipio>/` — navegação geográfica
  (seção 4.6); concursos `NACIONAL` aparecem em todos os recortes, estaduais também nos municípios da UF.
  Página de município só é gerada quando há concurso daquele município (evita milhares de páginas vazias e o
  limite de arquivos da Cloudflare).
- `/area/<area>/`, `/nivel/<nivel>/` — páginas de entrada para buscas no Google.
- `/isencoes/` e `/isencoes/<tipo>/` — explicação de cada isenção + concursos abertos que a preveem.
- `/alertas/` — formulário (nome, e-mail, filtro) [fase 7]; `/privacidade/`; `/sobre/` (fontes e limitações).

Requisitos: HTML semântico, mobile first, leve (sem framework JS pesado), contraste e navegação por teclado
(WCAG AA), `title`/`meta description` por página, dados estruturados (JSON-LD), `sitemap.xml`, URL canônica,
data de atualização visível. Rodapé com aviso: *"Informações extraídas automaticamente de fontes oficiais.
Confira sempre o edital."*

---

## 8. Estrutura do repositório

```
nqntech-concursos/                 (repositório PÚBLICO)
├── .github/workflows/             ci.yml, migrar.yml, diario.yml (coleta → site → alertas), ensaio.yml
├── .github/dependabot.yml
├── CLAUDE.md                      instruções de trabalho do Claude (leia primeiro)
├── docs/                          CONTEXTO_PROJETO.md, GUIA_PROMPTS.md, PENDENCIAS.md
├── db/migrations/  db/seeds/  db/tests/
├── config/                        areas.yml, escolaridade.yml, destaques.yml (CNU), isencoes.yml (textos das
│                                  páginas de isenção, fase 3), parceiros.yml (fase 9)
├── coletor/                       Python (base do Radar TI)
│   └── src/coletor/  fontes/  pipeline/  extratores/  classificacao/  resumo/
├── site/                          Java: gerador do site estático (Thymeleaf) + templates + css/js
├── alertas/                       Java: envio dos alertas (fase 7)
├── api/                           Java: API de cadastro (fase 7)
└── scripts/
```

---

## 9. Convenções de código
As mesmas do Radar TI: nível profissional, SOLID onde fizer sentido, erros explícitos, logs úteis, type hints,
records/dataclasses imutáveis, comentários só no não trivial, Javadoc/docstring só em contratos públicos,
testes para toda lógica relevante **sem internet**, ruff no Python. Nomes de domínio em português.

---

## 10. Segurança, privacidade e ética

### Segredos
- Repositório público: **nenhum segredo no código**; tudo em GitHub Secrets. `.env.example` fictício.
- Credencial de administrador do banco só no `migrar.yml`. Papéis com privilégio mínimo:
  `coletor_app`, `site_app` (só leitura do que é público), `alertas_app`, `api_app` (só assinantes/tokens).
- RLS em todas as tabelas; schema fechado para `PUBLIC`; testes SQL provando as permissões (como no Radar TI).

### Dados pessoais (LGPD)
- Coletar **só nome, e-mail e filtro**. Base legal: consentimento, registrado com data e versão da política.
- **Double opt-in**: nada é enviado antes da confirmação pelo link recebido.
- Sem senha: gerenciar filtro e descadastrar por **links com token de uso único/expiração**; no banco fica só o
  **hash** do token.
- Descadastro em um clique em todo e-mail; descadastro **apaga** os dados.
- **O filtro de isenção é só "com qualquer isenção"**: não guardar qual isenção a pessoa usaria (revelaria
  situação socioeconômica ou de saúde). Filtrar por tipo específico existe apenas na busca do site, sem cadastro.
- Política de privacidade simples e honesta, publicada em `/privacidade/`.
- API: validação de entrada, limite de requisições por IP, proteção anti-robô no formulário (ex.: desafio
  invisível gratuito), CORS restrito ao domínio do site, nunca revelar se um e-mail já está cadastrado.
- Logs sem e-mail completo (mascarar).

### Coleta
- Mesmas regras do Radar TI: robots.txt, domínios permitidos, intervalo por domínio, User-Agent identificado,
  **nunca contornar anti-bot/CAPTCHA**, PDFs só lidos e descartados.

### Conteúdo
- Resumos próprios, gerados a partir de fatos; **nunca copiar** texto de notícias; sempre linkar o oficial.
- Informação sobre isenção é orientação geral, com aviso para conferir o edital.

### Monetização
- A informação (site e alertas) é **sempre gratuita**. Se os custos superarem a receita, o **volume** pode ser
  limitado (ex.: alerta só semanal, fila de novos assinantes), com aviso prévio aos assinantes; nunca cobrar.
- Ordem prevista: **doações** primeiro; **afiliados** sempre identificados como publicidade e separados do
  resumo (o resumo nunca recomenda produto); **anúncios** só com banner de consentimento de cookies e política
  de privacidade atualizada, sem pesar o site em celular fraco.
- Licenças: código MIT (`LICENSE`); textos próprios do site CC BY 4.0 (`LICENSE-CONTEUDO.md`).

---

## 11. Roteiro por fases

| Fase | Entrega | Pronto quando… |
|---|---|---|
| 0 | Repositório público, base copiada do Radar TI (coletor, db, CI), schema `concursos`, Neon novo | CI verde |
| 1 | Banco ampliado: áreas, isenções, slug, resumo, campos do site, papéis | Testes SQL de permissão verdes |
| 2 | Coletor FGV completo: todas as áreas, níveis, UF, encerrados recentes, classificador de área | Concursos FGV classificados por área |
| 3 | Isenções + calendário, disciplinas e redação por cargo (FGV) | TJPB 2026 com os 5 tipos, o prazo e o calendário |
| 4 | Resumo automático + slug + campos desnormalizados | Resumo correto para os concursos de teste |
| 5 | **Site estático** na Cloudflare: páginas, filtros, isenções, sitemap, SEO, domínio próprio | **Site no ar (MVP)** |
| 6 | Mais fontes: DOU (INLABS), Querido Diário, Vunesp/Selecon (se liberarem) + deduplicação | Cobertura nacional crescente |
| 7 | Alertas: API de cadastro, double opt-in, links mágicos, envio diário/semanal, privacidade | Assinante recebe alerta do seu filtro |
| 8 | Robustez: monitoramento, retenção, backup, alertas de falha para o administrador | Serviço se mantém sozinho |
| 9 | (Opcional) Painel administrativo Angular, resumo por LLM, monetização (doações → afiliados → anúncios) | — |

---

## 12. Estado atual

- [x] Ideia e decisões (29/10/2026): site público e gratuito; todas as áreas/níveis/estados; previstos, abertos
      e encerrados; resumo por concurso; isenções; alertas com cadastro só de nome + e-mail + filtro
- [x] Decisões técnicas: repositório público `nqntech-concursos`; coleta no GitHub Actions; site estático
      Thymeleaf; Neon em projeto separado; Angular só em painel administrativo opcional
- [x] Documentos só no repositório (29/10/2026): `docs/` + `CLAUDE.md` com as instruções; o Projeto no Claude
      fica sem arquivos e sem instruções, e cada conversa começa lendo o repositório
- [x] Licenças: MIT (código) + CC BY 4.0 (textos do site)
- [x] Hospedagem: Cloudflare (Workers com assets estáticos, grátis) com domínio próprio, no lugar do GitHub
      Pages; site estático regenerado após cada coleta; filtros no navegador; cadastro de alertas é a única
      parte com servidor
- [x] Monetização prevista (doações, afiliados, anúncios) com informação sempre gratuita
- [x] Fase 0 — Repositório e base (29/10/2026): coletor Python herdado do Radar TI **sem o filtro de TI**
      (fontes FGV, IBAM e IBADE; todos os editais de concursos ativos são lidos), schema `concursos`, papéis
      `coletor_app` e `site_app` (só leitura, sessão read-only, sem acesso a texto de editais nem a sinais) com
      RLS e testes SQL; workflows `ci` (com gitleaks), `migrar`, `diario`, `ensaio` e captura. CI verde; ensaio
      com coleta real gravou 163 concursos das 3 fontes. Pendente com o usuário: Neon novo e secrets
      (`docs/PENDENCIAS.md`).
      Observações para as próximas fases: Vunesp e Selecon (fase 6) respondem 403 a servidores desde 29/10/2026
      e ficam com `coleta_permitida = false` (não contornar); o órgão de alguns títulos da FGV sai incompleto
      (ex.: "5ª Região"), a revisar na fase 2.
- [x] Neon `nqntech_concursos` criado, secrets cadastrados e `migrar` verde (29/10/2026)
- [x] Fase 1 — Banco ampliado (29/10/2026): migrations V5–V9 com regiões, UFs e os municípios do IBGE (V6 gerada
      pelo workflow `captura-ibge`; a API do IBGE não responde ao GitHub Actions, então a lista veio do espelho
      público `kelvins/municipios-brasileiros`, derivado do IBGE, 5.571 municípios, registrado no cabeçalho), catálogos de área, escolaridade e isenção, campos do
      site em `concurso` (slug, abrangência, UF/município, desnormalizados, isenção, resumo, `publicado`,
      `encerrado_em`), `concurso_isencao`, `concurso_evento` (calendário), disciplinas e redação por cargo,
      índices das páginas e RLS do `site_app` restrita a concursos publicados. Seeds com 8 concursos (nacional,
      estaduais, municipais, com/sem isenção, previsto, encerrado e um não publicado). Testes SQL: lista branca
      do `site_app`, integridade dos campos e catálogos. Concursos já coletados ficam `publicado = false` até as
      fases 2–4 preencherem slug, abrangência e resumo. `alertas_app`/`api_app` continuam para a fase 7.
- [x] Revisão dos documentos (29/10/2026): tela inicial ordenada por CNU → nacionais → demais e prova mais
      próxima; encerrados saem do site após 180 dias; calendário/disciplinas/redação explícitos na fase 3;
      conta Cloudflare criada, deploy só pelo GitHub Actions (repositório **não** conectado à Cloudflare);
      token e Account ID em `docs/PENDENCIAS.md`.
- [x] Fase 2 — Coletor FGV completo (29/10/2026, PR #1):
      - FGV lê também o bloco "realizados" (`COLETOR_MAX_PAGINAS_REALIZADOS`, padrão 2): concurso movido para lá
        vira `ENCERRADO` com `encerrado_em` = data da última publicação; encerrado nunca acompanhado só entra se
        for dos últimos 180 dias (senão o sinal fica `DESCARTADO`); se voltar a "em andamento", é reaberto.
      - Nova etapa `classificar` (depois de `estruturar`), que recalcula tudo e grava só o que mudou: área do cargo
        (`config/areas.yml`: palavra inteira, termo mais longo vence, exclusões, abreviações, órgão e palavras
        genéricas como últimos recursos; sem regra → `OUTRAS` com aviso no log), escolaridade faltante
        (`config/escolaridade.yml`, conservador), abrangência/UF/município do IBGE (homônimos pela UF citada na
        página/edital; capital como desempate) e CNU (`config/destaques.yml` → `concurso.unificado`, V10).
      - Órgão inferido corrigido (hífen em "Procuradoria-Geral", região dos TRTs/TRFs, sigla com UF, texto antes
        do órgão, DF); órgão federal de um estado só vira estadual (TRT da 13ª → PB, TRF da 6ª → MG).
      - Extrator FGV: sem quadro de vagas legível, cargos vêm do anexo de remuneração, dos títulos
        "CARGO: ... - PERFIL: ..."/"CARGO DE NÍVEL ..." ou da abertura do edital, com aviso "confira o edital".
      - Páginas sem charset no cabeçalho (IBAM, windows-1252) passam a ser lidas pelo `<meta charset>`; o IBADE
        deixou de gerar "cargos" com a unidade de lotação ("UN: EMEF ... - TIPOLOGIA").
      - Ensaio com coleta real (165 concursos, 20 editais lidos): 158 com local definido (7 sem pista suficiente),
        CNU 2 identificado e nacional; 589 cargos, 581 (98,6%) com área e 8 em `OUTRAS` (listados no resumo do
        ensaio para afinar `config/areas.yml`).
      Observações: editais que só trazem o quadro em tabela por localidade ficam sem vagas por cargo (aviso
      "confira o edital"); alguns órgãos sem pista de esfera/UF (ex.: estatais federais pouco conhecidas)
      ficam sem local e não são publicados até uma regra os reconhecer.
- [ ] Fase 3 — Isenções + calendário, disciplinas e redação por cargo
