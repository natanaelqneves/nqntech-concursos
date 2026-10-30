# NqnTech Concursos — Guia de construção com o Claude

> Como usar: para cada fase da Parte 2, abra uma conversa no Projeto e cole a **abertura** (abaixo) seguida do
> prompt da fase (pode ser a mesma conversa para várias fases, se o contexto estiver curto). Ao fim de cada
> fase, o `CONTEXTO_PROJETO.md` é atualizado no repositório.
> O Claude cria o repositório, escreve o código, roda os testes no GitHub Actions e deixa com você só o que
> depende das suas contas (com instruções em `docs/PENDENCIAS.md`).
>
> **Documentos só no repositório:** `CLAUDE.md` (instruções de trabalho) e `docs/` (contexto, guia,
> pendências). O Projeto no Claude não guarda arquivos nem instruções; nada precisa ser sincronizado.
>
> **Abertura** (primeira linha de toda conversa nova):
> `Repositório https://github.com/natanaelqneves/nqntech-concursos — leia CLAUDE.md e docs/CONTEXTO_PROJETO.md antes de tudo.`

---

## Parte 1 — Preparar (uma vez, ~10 min)

1. **GitHub:** crie o repositório **vazio** e **público** `nqntech-concursos` em <https://github.com/new>
   (sem README, sem .gitignore, sem licença). O Claude não consegue criar repositórios na sua conta, só usar
   um que já existe.
2. **Claude:** crie um Projeto novo chamado **NqnTech Concursos** (sem arquivos e sem instruções: tudo fica no
   repositório, em `CLAUDE.md` e `docs/`).
3. Abra uma conversa nova no Projeto e cole a **abertura** e o prompt da **Fase 0**.

O Neon (projeto novo) e a Cloudflare são configurados quando a fase pedir; o Claude avisa e explica.

---

## Parte 2 — Prompts por fase

### Fase 0 — Repositório e base

```
Fase 0 — Repositório e base do NqnTech Concursos.

O repositório vazio é https://github.com/natanaelqneves/nqntech-concursos (público).
Use como ponto de partida o motor do Radar TI (https://github.com/natanaelqneves/radar-ti, meu), SEM alterar
o radar-ti: copie o que serve (coletor Python, migrations, testes SQL, CI, ensaio, scripts de apoio) e adapte:
- schema "concursos" no lugar de "radar"; papéis coletor_app, site_app, alertas_app, api_app (os dois últimos
  podem nascer só na fase 7);
- remova o que é específico do uso pessoal (notificador Java do Radar TI, perfil.yml de TI);
- docs/ com CONTEXTO_PROJETO.md, GUIA_PROMPTS.md e PENDENCIAS.md, e CLAUDE.md na raiz;
- LICENSE (sugira uma e me pergunte antes) e README voltado ao público.
Rode a CI no GitHub e me diga o que ficou pendente comigo (Neon novo, secrets).
```

### Fase 1 — Banco ampliado

```
Fase 1 — Modelo de dados da seção 5 do contexto.
Migrations com: áreas (catálogo), isenção (catálogo + concurso_isencao), slug, uf/municipio, campos
desnormalizados para o site, resumo, situação ENCERRADO; índices para as páginas do site (por UF, área,
situação, isenção) e papéis com privilégio mínimo + RLS. Seeds de dev com concursos de várias áreas/UFs,
alguns com isenção. Testes SQL de permissão (incluindo site_app só leitura e sem acesso a dados pessoais).
```

### Fase 2 — Coletor FGV completo

```
Fase 2 — Coletor FGV para todas as áreas.
- Descoberta também dos encerrados recentes (bloco "realizados"), com limite de páginas configurável.
- config/areas.yml com termos por área (seção 4.1) e classificador de área do cargo, com testes por área
  (incluindo casos ambíguos e termos de exclusão).
- Escolaridade, abrangência (NACIONAL/ESTADUAL/MUNICIPAL), UF e município IBGE do concurso; situação por datas.
- Revisar o órgão incompleto em alguns títulos da FGV (ex.: "5ª Região").
- Migration com concurso.unificado e config/destaques.yml com as regras que identificam o CNU (seção 4.6).
- Reaproveite as fixtures reais do TJPB 2026; capture mais fixtures da FGV pelo workflow de captura
  (concursos de áreas diferentes: saúde, educação, policial).
```

### Fase 3 — Isenções

```
Fase 3 — Isenções de taxa.
- config/isencoes.yml com o catálogo da seção 4.4: nome, descrição curta em linguagem simples, documentos
  usuais e base legal citada nos editais, com link oficial (confira cada link na web antes de colocar).
- Extrator da seção de isenção dos editais FGV: tipos previstos e período para pedir; avisos quando incerto.
- Extrator do calendário (concurso_evento: evento, início, fim; "a definir" sem data), da lista de
  disciplinas por cargo (só os nomes, nunca o conteúdo programático) e de tem_redacao (NULL quando incerto).
- Teste com o edital TJPB 2026 real: CadÚnico, doadores de sangue/medula, jurados, vítimas de violência
  doméstica e doadores de plasma, período de isenção e calendário.
Linguagem sempre informativa ("o edital prevê"), nunca "você tem direito".
```

### Fase 4 — Resumo automático

```
Fase 4 — Resumo de cada concurso (seção 4.5): texto próprio gerado por regras a partir dos campos
estruturados, omitindo o que faltar, em português simples (frases curtas). Gere também slug estável e os
campos desnormalizados. Testes com concursos completos e incompletos (sem salário, sem data de prova,
previstos sem edital).
```

### Fase 5 — Site estático (MVP público)

```
Fase 5 — Site estático (seções 2 e 7 do contexto).
- Módulo site/ em Java 25 + Spring Boot 4.1 (linha de comando) + Thymeleaf gerando HTML em uma pasta,
  conectando como site_app.
- Páginas: início (só inscrições abertas, ordem da seção 4.6: CNU → nacionais → demais, prova mais próxima
  primeiro), lista com filtros no navegador (busca.json), página de cada concurso, navegação Brasil → região →
  estado → município (município só com concurso), por área, por nível, isenções (índice e por tipo), sobre,
  privacidade (rascunho). Encerrados há mais de 180 dias ficam fora do site.
- SEO: title/description por página, JSON-LD, sitemap.xml, robots.txt, URLs canônicas.
- Acessibilidade WCAG AA, mobile first, CSS próprio leve, sem framework JS pesado.
- Workflow que, depois da coleta diária, gera o site (só o que mudou) e publica na Cloudflare com
  wrangler pelo GitHub Actions (Worker só de assets, sem script, domínio próprio; secrets CLOUDFLARE_API_TOKEN
  e CLOUDFLARE_ACCOUNT_ID já cadastrados). Sem integração Git na Cloudflare. Me diga o que falta no domínio.
- Testes: geração com os seeds, links internos sem quebra, HTML escapado (dado coletado é não confiável).
```

### Fase 6 — Mais fontes

```
Fase 6 — Novas fontes e deduplicação, uma por vez: DOU via INLABS, Querido Diário (o CNU já vem pela FGV);
Vunesp e Selecon só se pararem de bloquear servidores (403 em 29/10/2026; nunca contornar).
Antes de cada fonte, confira robots.txt e termos de uso e me diga o resultado. Fixtures reais capturadas pelo
GitHub Actions. Deduplicação com a ordem de chaves do contexto; casos duvidosos marcados possivel_duplicado.
```

### Fase 7 — Alertas por e-mail

```
Fase 7 — Cadastro e alertas (seção 10 do contexto).
- Compare 2 ou 3 opções gratuitas atuais para hospedar a API Spring Boot e para enviar e-mail transacional
  (limites, cold start, exigências), confira na documentação oficial e me recomende uma.
- API: cadastro (nome, e-mail, filtro: UFs, áreas, níveis, só com isenção, frequência), double opt-in, links
  mágicos com token de uso único (só o hash no banco), descadastro que apaga os dados, limite por IP,
  proteção anti-robô, CORS restrito.
- Formulário em /alertas/ do site e página de privacidade final.
- Job de alertas no workflow diário: nunca repetir concurso para o mesmo assinante; versão semanal.
- Testes com Testcontainers + GreenMail.
```

### Fase 8 — Robustez

```
Fase 8 — Monitoramento e manutenção: e-mail para o administrador quando a coleta falhar 2 dias seguidos ou
uma fonte ficar 7 dias sem novidade; retenção da seção 5; backup mensal; página /sobre/ com a data da última
atualização e a cobertura por fonte.
```

---

## Parte 3 — Prompts de apoio

**Corrigir erro** — "Ao rodar [workflow/comando], aconteceu este erro: [cole tudo]. Explique a causa antes da
correção."

**Revisão de segurança** — "Revise a fase atual contra a seção 10 do contexto e liste problemas por gravidade."

**Retomar** — "Estou retomando a fase [X]. Leia o CONTEXTO_PROJETO.md e o estado do repositório e continue."

---

## Boas práticas
- Nunca cole senhas, connection strings ou secrets na conversa.
- Repositório público: confira antes de cada commit que nada sensível entrou (a CI também verifica).
- O Radar TI continua independente: mudanças no NqnTech não mexem nele.
- `CLAUDE.md` e `docs/` mudam só por commit no Git; não existem cópias em outro lugar.
