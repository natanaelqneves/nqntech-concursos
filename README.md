# NqnTech Concursos

Site **público e gratuito** de concursos públicos do Brasil: previstos, abertos e encerrados, de todas as áreas,
níveis e estados, com resumo próprio de cada concurso, destaque para as **isenções de taxa** e alertas por
e-mail. Objetivo: democratizar o acesso a concursos com informação direta, simples e sempre com link para o
edital oficial.

> Projeto em construção. Acompanhe o andamento em [`docs/CONTEXTO_PROJETO.md`](docs/CONTEXTO_PROJETO.md)
> (seção "Estado atual").

## Como funciona

```
Fontes oficiais ──► Coletor (Python) ──► PostgreSQL ──► Gerador do site (Java/Thymeleaf) ──► site estático
(bancas, diários)   descobre, lê editais,                páginas, filtros, sitemap
                    estrutura e resume
```

- Tudo roda uma vez por dia no GitHub Actions; o site é estático (rápido, leve e seguro).
- A coleta respeita `robots.txt`, identifica-se com um contato e **nunca contorna bloqueios ou CAPTCHAs**.
  Os PDFs dos editais são lidos e descartados; o site guarda apenas os dados estruturados e o link oficial.
- Os resumos são escritos automaticamente a partir dos dados do edital, nunca copiados de notícias.

**As informações são extraídas automaticamente de fontes oficiais e podem conter erros. Confira sempre o
edital.**

## Estrutura

| Pasta | Conteúdo |
|---|---|
| `coletor/` | Coletor em Python 3.13: fontes, pipeline, extratores de edital |
| `db/` | Migrations (Flyway), seeds de desenvolvimento e testes de permissão em SQL |
| `scripts/` | Ambiente local, utilitários de CI e captura de fixtures |
| `docs/` | Contexto do projeto (fonte da verdade), guia de construção e pendências |
| `site/`, `alertas/`, `api/` | Gerador do site e alertas em Java (próximas fases) |

## Rodar localmente

Pré-requisitos: Docker e Python 3.13.

```bash
./scripts/subir.sh --email voce@exemplo.com      # Windows: .\scripts\subir.ps1 -Email voce@exemplo.com
python -m venv .venv && . .venv/bin/activate
pip install -e "coletor[dev]"
python -m coletor descobrir --fonte fgv --dry-run  # só mostra o que encontraria
python -m coletor executar --limite 5              # pipeline completo, até 5 editais
```

O `subir.sh` cria o `.env` com senhas locais aleatórias, sobe Postgres + Flyway + Mailpit (só em
`127.0.0.1`) e verifica o ambiente.

Testes (sem internet; os de banco rodam quando `TESTE_DB_*` está definido, como na CI):

```bash
cd coletor && pytest -q && ruff check src tests
```

## Licença

Código sob [MIT](LICENSE). Textos próprios do site (resumos, páginas de isenção) sob
[CC BY 4.0](LICENSE-CONTEUDO.md). Editais e documentos oficiais pertencem aos órgãos e bancas que os publicam.
