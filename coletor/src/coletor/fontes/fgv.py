"""Fonte FGV Conhecimento: aba "Em andamento" de https://conhecimento.fgv.br/concursos.

Estrutura observada em 29/10/2026 (Drupal):
- listagem: bloco `.view-concursos-em-andamento` com `.views-row a` e paginação `?page=N` (0-based),
  compartilhada com o bloco "realizados", que ignoramos;
- página do concurso: `h1`, status em `.field--name-field-concurso-status`, descrição em `.field--name-body`
  e "Arquivos do concurso" em `.field--name-field-concurso-arquivos .paragraph` (data em <time datetime>).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from coletor.fontes.base import ResultadoDescoberta, SinalDescoberta
from coletor.http_cliente import ClienteHttp, ErroHttp
from coletor.texto import colapsar_espacos, normalizar

log = logging.getLogger(__name__)

BASE = "https://conhecimento.fgv.br"
LISTAGEM = f"{BASE}/concursos"
MAX_DESCRICAO = 4000

# A aba "em andamento" mistura concursos com exames de certificação, residências e vestibulares.
_PREFIXOS_IGNORADOS = ("/exames/",)
_TITULOS_IGNORADOS = re.compile(
    r"\b(exame|residencia|vestibular|processo seletivo para a faculdade|selecao de estudantes|bolsa)\b"
)


@dataclass(frozen=True)
class ItemListagem:
    titulo: str
    url: str


@dataclass(frozen=True)
class PaginaListagem:
    itens: tuple[ItemListagem, ...]
    ultima_pagina: int


def parse_listagem(html: str) -> PaginaListagem:
    soup = BeautifulSoup(html, "lxml")
    bloco = soup.select_one("div.view-concursos-em-andamento")
    if bloco is None:
        raise ErroHttp("listagem da FGV sem o bloco 'concursos em andamento' (o layout do site mudou?)")
    itens = []
    for link in bloco.select(".views-row a[href]"):
        titulo = colapsar_espacos(link.get_text(" "))
        if titulo:
            itens.append(ItemListagem(titulo=titulo, url=canonizar(urljoin(BASE, str(link["href"])))))
    paginas = [0]
    for link in bloco.select("a[href*='page=']"):
        valores = parse_qs(urlsplit(str(link["href"])).query).get("page", [])
        paginas.extend(int(v) for v in valores if v.isdigit())
    return PaginaListagem(tuple(itens), max(paginas))


def eh_concurso(item: ItemListagem) -> bool:
    caminho = urlsplit(item.url).path
    if any(caminho.startswith(prefixo) for prefixo in _PREFIXOS_IGNORADOS):
        return False
    return _TITULOS_IGNORADOS.search(normalizar(item.titulo)) is None


def parse_concurso(html: str, url: str) -> dict:
    """Dados da página do concurso, no formato gravado em sinal_descoberta.payload."""
    soup = BeautifulSoup(html, "lxml")
    principal = soup.find("main") or soup
    titulo_tag = principal.find("h1")
    status = principal.select_one(".field--name-field-concurso-status .field__item")
    corpo = principal.select_one(".field--name-body")

    arquivos = []
    for paragrafo in principal.select(".field--name-field-concurso-arquivos .paragraph"):
        link = paragrafo.select_one("a[href]")
        if link is None:
            continue
        arquivos.append(
            {
                "titulo": colapsar_espacos(link.get_text(" ")),
                "url": urljoin(url, str(link["href"])),
                "data": _data_do_paragrafo(paragrafo),
            }
        )

    return {
        "fonte": "fgv",
        "titulo": colapsar_espacos(titulo_tag.get_text(" ")) if titulo_tag else None,
        "situacao_site": colapsar_espacos(status.get_text(" ")) if status else None,
        "descricao": colapsar_espacos(corpo.get_text(" "))[:MAX_DESCRICAO] if corpo else None,
        "link_inscricao": _link_inscricao(principal),
        "arquivos": arquivos,
    }


def canonizar(url: str) -> str:
    partes = urlsplit(url)
    return f"{partes.scheme}://{partes.netloc.lower()}{partes.path.rstrip('/')}"


def _data_do_paragrafo(paragrafo: Tag) -> str | None:
    tempo = paragrafo.find("time")
    if tempo is None:
        return None
    valor = str(tempo.get("datetime") or "")
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        texto = tempo.get_text(strip=True)
        try:
            return datetime.strptime(texto, "%d/%m/%Y").date().isoformat()
        except ValueError:
            return None


def _link_inscricao(principal: Tag) -> str | None:
    for link in principal.select("a[href]"):
        texto = normalizar(link.get_text(" "))
        href = str(link["href"])
        if href.startswith("https://") and ("inscreva" in texto or "/inscricao" in href.lower()):
            return href
    return None


class FonteFGV:
    nome = "fgv"
    dominios = frozenset({"conhecimento.fgv.br"})

    def __init__(self, max_paginas: int = 15) -> None:
        self._max_paginas = max_paginas

    def descobrir(self, http: ClienteHttp) -> ResultadoDescoberta:
        itens = self._listar(http)
        log.info("FGV: %d itens na aba 'em andamento' que parecem concursos", len(itens))
        sinais: list[SinalDescoberta] = []
        falhas: list[str] = []
        for item in itens:
            try:
                payload = parse_concurso(http.obter_texto(item.url), item.url)
            except ErroHttp as erro:
                log.warning("FGV: falha ao ler %s: %s", item.url, erro)
                falhas.append(f"{item.url}: {erro}")
                continue
            datas = [date.fromisoformat(a["data"]) for a in payload["arquivos"] if a["data"]]
            sinais.append(
                SinalDescoberta(
                    titulo=payload["titulo"] or item.titulo,
                    url=item.url,
                    data_publicacao=max(datas) if datas else None,
                    payload=payload,
                )
            )
        return ResultadoDescoberta(tuple(sinais), tuple(falhas))

    def _listar(self, http: ClienteHttp) -> list[ItemListagem]:
        # A primeira página é obrigatória: se falhar, a fonte inteira falhou (a exceção sobe).
        primeira = parse_listagem(http.obter_texto(LISTAGEM))
        ultima = min(primeira.ultima_pagina, self._max_paginas - 1)
        itens = list(primeira.itens)
        for pagina in range(1, ultima + 1):
            itens.extend(parse_listagem(http.obter_texto(f"{LISTAGEM}?page={pagina}")).itens)
        vistos: dict[str, ItemListagem] = {}
        for item in itens:
            if eh_concurso(item):
                vistos.setdefault(item.url, item)
        return list(vistos.values())
