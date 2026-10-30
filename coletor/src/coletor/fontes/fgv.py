"""Fonte FGV Conhecimento: blocos "Em andamento" e "Realizados" de https://conhecimento.fgv.br/concursos.

Estrutura observada em 29/10/2026 (Drupal):
- listagem: blocos `.view-concursos-em-andamento` e `.view-concursos-realizados`, cada um com `.views-row a`;
  os dois compartilham a paginação `?page=N` (0-based): a página N traz a N-ésima página de cada bloco;
- "realizados" lista os concursos já finalizados, dos mais novos para os mais antigos: lemos só as primeiras
  páginas, o bastante para perceber quando um concurso que acompanhamos sai de "em andamento";
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
    encerrado: bool = False


@dataclass(frozen=True)
class Bloco:
    itens: tuple[ItemListagem, ...]
    ultima_pagina: int


@dataclass(frozen=True)
class PaginaListagem:
    andamento: Bloco
    realizados: Bloco

    @property
    def itens(self) -> tuple[ItemListagem, ...]:
        return self.andamento.itens

    @property
    def ultima_pagina(self) -> int:
        return self.andamento.ultima_pagina


def parse_listagem(html: str) -> PaginaListagem:
    soup = BeautifulSoup(html, "lxml")
    andamento = soup.select_one("div.view-concursos-em-andamento")
    if andamento is None:
        raise ErroHttp("listagem da FGV sem o bloco 'concursos em andamento' (o layout do site mudou?)")
    realizados = soup.select_one("div.view-concursos-realizados")
    if realizados is None:
        log.warning("FGV: listagem sem o bloco 'concursos realizados'; encerrados não serão detectados por ele")
    return PaginaListagem(
        andamento=_parse_bloco(andamento, encerrado=False),
        realizados=_parse_bloco(realizados, encerrado=True) if realizados is not None else Bloco((), 0),
    )


def _parse_bloco(bloco: Tag, encerrado: bool) -> Bloco:
    itens = []
    for link in bloco.select(".views-row a[href]"):
        titulo = colapsar_espacos(link.get_text(" "))
        if titulo:
            url = canonizar(urljoin(BASE, str(link["href"])))
            itens.append(ItemListagem(titulo=titulo, url=url, encerrado=encerrado))
    paginas = [0]
    for link in bloco.select("a[href*='page=']"):
        valores = parse_qs(urlsplit(str(link["href"])).query).get("page", [])
        paginas.extend(int(v) for v in valores if v.isdigit())
    return Bloco(tuple(itens), max(paginas))


def eh_concurso(item: ItemListagem) -> bool:
    caminho = urlsplit(item.url).path
    if any(caminho.startswith(prefixo) for prefixo in _PREFIXOS_IGNORADOS):
        return False
    return _TITULOS_IGNORADOS.search(normalizar(item.titulo)) is None


def parse_concurso(html: str, url: str, encerrado: bool = False) -> dict:
    """Dados da página do concurso, no formato gravado em sinal_descoberta.payload.

    `encerrado` = o concurso estava no bloco "realizados" da listagem (a FGV já o deu por finalizado).
    """
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
        "encerrado": encerrado,
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

    def __init__(self, max_paginas: int = 15, max_paginas_realizados: int = 0) -> None:
        self._max_paginas = max_paginas
        self._max_paginas_realizados = max_paginas_realizados

    def descobrir(self, http: ClienteHttp, pular: frozenset[str] = frozenset()) -> ResultadoDescoberta:
        listados = self._listar(http)
        itens = [item for item in listados if item.url not in pular]
        encerrados = sum(item.encerrado for item in listados)
        log.info(
            "FGV: %d itens que parecem concursos (%d em andamento, %d realizados); %d páginas a ler, %d sem "
            "oportunidade aberta ficam para a releitura semanal",
            len(listados),
            len(listados) - encerrados,
            encerrados,
            len(itens),
            len(listados) - len(itens),
        )
        sinais: list[SinalDescoberta] = []
        falhas: list[str] = []
        for numero, item in enumerate(itens, start=1):
            if numero % 25 == 0:
                log.info("FGV: %d/%d páginas lidas", numero, len(itens))
            try:
                payload = parse_concurso(http.obter_texto(item.url), item.url, encerrado=item.encerrado)
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
        ultima_andamento = min(primeira.andamento.ultima_pagina, self._max_paginas - 1)
        ultima_realizados = min(primeira.realizados.ultima_pagina, self._max_paginas_realizados - 1)
        andamento = list(primeira.andamento.itens)
        realizados = list(primeira.realizados.itens) if ultima_realizados >= 0 else []
        for pagina in range(1, max(ultima_andamento, ultima_realizados) + 1):
            listagem = parse_listagem(http.obter_texto(f"{LISTAGEM}?page={pagina}"))
            if pagina <= ultima_andamento:
                andamento.extend(listagem.andamento.itens)
            if pagina <= ultima_realizados:
                realizados.extend(listagem.realizados.itens)
        # "Em andamento" vence: um concurso visto nos dois blocos (a listagem muda durante a leitura) não é
        # dado por encerrado.
        vistos: dict[str, ItemListagem] = {}
        for item in [*andamento, *realizados]:
            if eh_concurso(item):
                vistos.setdefault(item.url, item)
        return list(vistos.values())
