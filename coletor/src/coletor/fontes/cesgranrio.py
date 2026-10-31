"""Fonte Cesgranrio: concursos em andamento, concluídos e inscrições abertas em https://www.cesgranrio.org.br/concursos/.

Estrutura observada:
- Listagem baseada em WordPress / Uncode Theme (Isotope grid).
- Cards em `.tmb`, com links `a[href*='/concurso/']` e títulos em `h3.t-entry-title`.
- Categorias mapeadas pelas classes da grid:
  - `grid-cat-25`: EM ANDAMENTO
  - `grid-cat-27`: INSCRIÇÕES ABERTAS
  - `grid-cat-26`: CONCLUÍDOS
- Paginação no rodape via `ul.pagination a[href*='/concursos/page/']`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from coletor.fontes.base import ResultadoDescoberta, SinalDescoberta
from coletor.http_cliente import ClienteHttp, ErroHttp
from coletor.texto import colapsar_espacos, normalizar

log = logging.getLogger(__name__)

BASE = "https://www.cesgranrio.org.br"
LISTAGEM = f"{BASE}/concursos/"

# Concursos de vestibular não são concursos públicos para cargos.
_TITULOS_IGNORADOS = re.compile(r"\b(vestibular|pisa para escolas|certificacao)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ItemListagem:
    titulo: str
    url: str
    situacao: str


def parse_listagem(html: str) -> tuple[list[ItemListagem], int]:
    """Retorna a lista de concursos encontrados na página e o número total de páginas da listagem."""
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select(".tmb")
    if not cards:
        raise ErroHttp("Listagem da Cesgranrio sem cards de concurso (o layout do site mudou?)")

    itens: list[ItemListagem] = []
    for card in cards:
        link_title = card.select_one("h3.t-entry-title a[href]")
        if not link_title:
            continue

        titulo = colapsar_espacos(link_title.get_text(" "))
        url = canonizar(urljoin(BASE, str(link_title["href"])))

        # Ignorar vestibulares ou certificações
        if _TITULOS_IGNORADOS.search(normalizar(titulo)):
            continue

        # Mapeamento de situação baseado nas classes do card
        classes = card.get("class", [])
        if "grid-cat-27" in classes:
            situacao = "INSCRICOES_ABERTAS"
        elif "grid-cat-25" in classes:
            situacao = "EM_ANDAMENTO"
        else:
            situacao = "ENCERRADO"

        itens.append(ItemListagem(titulo=titulo, url=url, situacao=situacao))

    # Descobrir última página
    paginas = [1]
    for link in soup.select("ul.pagination a[href*='/concursos/page/']"):
        m = re.search(r"/page/(\d+)", str(link["href"]))
        if m:
            paginas.append(int(m.group(1)))

    return itens, max(paginas)


def parse_concurso(html: str, url: str, situacao_site: str) -> dict:
    """Extrai o conteúdo detalhado da página de um concurso específico da Cesgranrio."""
    soup = BeautifulSoup(html, "lxml")
    principal = soup.find("main") or soup.select_one(".page-wrapper") or soup

    titulo_tag = principal.select_one("h1, h2.h2, h3.t-entry-title")
    titulo = colapsar_espacos(titulo_tag.get_text(" ")) if titulo_tag else None

    # Descrição do concurso
    corpo = principal.select_one(".post-content, .entry-content, .t-entry-excerpt")
    descricao = colapsar_espacos(corpo.get_text(" ")) if corpo else None

    # Extração de arquivos (editais, retificações, cronogramas em PDF)
    arquivos = []
    for link in principal.select("a[href]"):
        href = str(link["href"])
        texto_link = colapsar_espacos(link.get_text(" "))
        if href.lower().endswith(".pdf") or "edital" in texto_link.lower():
            arquivos.append({
                "titulo": texto_link or "Documento do Concurso",
                "url": urljoin(url, href),
                "data": None,
                "pdf": href.lower().endswith(".pdf"),
            })

    # Link para sistema de inscrição/Portal do Candidato
    link_inscricao = None
    for link in principal.select("a[href]"):
        href = str(link["href"])
        if "concursos.cesgranrio.org.br" in href or "inscricao" in href.lower():
            link_inscricao = href
            break

    return {
        "fonte": "cesgranrio",
        "titulo": titulo,
        "situacao_site": situacao_site,
        "descricao": descricao,
        "link_inscricao": link_inscricao,
        "arquivos": arquivos,
    }


def canonizar(url: str) -> str:
    partes = urlsplit(url)
    return f"{partes.scheme}://{partes.netloc.lower()}{partes.path.rstrip('/')}/"


class FonteCESGRANRIO:
    nome = "cesgranrio"
    dominios = frozenset({"cesgranrio.org.br", "www.cesgranrio.org.br"})

    def __init__(self, max_paginas: int = 5, max_paginas_realizados: int = 0) -> None:
        self._max_paginas = max_paginas

    def descobrir(self, http: ClienteHttp, pular: frozenset[str] = frozenset()) -> ResultadoDescoberta:
        listados = self._listar(http)
        itens = [item for item in listados if item.url not in pular]

        log.info(
            "Cesgranrio: %d concursos encontrados; %d para processar",
            len(listados),
            len(itens),
        )

        sinais: list[SinalDescoberta] = []
        falhas: list[str] = []

        for item in itens:
            try:
                payload = parse_concurso(http.obter_texto(item.url), item.url, item.situacao)
                sinais.append(
                    SinalDescoberta(
                        titulo=payload["titulo"] or item.titulo,
                        url=item.url,
                        payload=payload,
                    )
                )
            except ErroHttp as erro:
                log.warning("Cesgranrio: falha ao ler %s: %s", item.url, erro)
                falhas.append(f"{item.url}: {erro}")

        return ResultadoDescoberta(tuple(sinais), tuple(falhas))

    def _listar(self, http: ClienteHttp) -> list[ItemListagem]:
        primeira_html = http.obter_texto(LISTAGEM)
        itens, ultima_pagina = parse_listagem(primeira_html)

        max_pag = min(ultima_pagina, self._max_paginas)
        for pagina in range(2, max_pag + 1):
            url_pag = f"{LISTAGEM}page/{pagina}/"
            try:
                html = http.obter_texto(url_pag)
                novos_itens, _ = parse_listagem(html)
                itens.extend(novos_itens)
            except ErroHttp as erro:
                log.warning("Cesgranrio: falha ao carregar pagina %d (%s)", pagina, erro)
                break

        vistos: dict[str, ItemListagem] = {}
        for item in itens:
            vistos.setdefault(item.url, item)

        return list(vistos.values())
