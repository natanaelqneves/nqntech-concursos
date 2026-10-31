"""Fonte Consulpam Concursos: listagem de concursos e editais de https://consulpam.com.br/.

Estrutura observada:
- Listagem principal em https://consulpam.com.br/index.php?menu=concursos
- Blocos divididos por tags <h2 class="tag"> (Inscrições Abertas, Próximos Concursos, Em Andamento)
- Tabelas contendo os links para os detalhes dos concursos e editais (index.php?menu=concursos&acao=ver&id=...)
  ou links externos para subdomínios de inscrição (ex: selecao.net.br).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from coletor.fontes.base import ResultadoDescoberta, SinalDescoberta
from coletor.http_cliente import ClienteHttp, ErroHttp
from coletor.texto import colapsar_espacos

log = logging.getLogger(__name__)

BASE = "https://consulpam.com.br"
LISTAGEM = f"{BASE}/index.php?menu=concursos"
MAX_DESCRICAO = 4000

# Termos para filtrar links irrelevantes ou de navegação genérica
_TITULOS_IGNORADOS = re.compile(
    r"\b(home|institucional|noticias|servicos|links|contato|facebook|instagram)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class ItemListagem:
    titulo: str
    url: str
    encerrado: bool = False
    situacao_site: str | None = None


@dataclass(frozen=True)
class PaginaListagem:
    itens: tuple[ItemListagem, ...]


def parse_listagem(html: str) -> PaginaListagem:
    soup = BeautifulSoup(html, "lxml")

    # O portal da Consulpam agrupa os concursos em blocos precedidos por tags h2.tag
    itens: list[ItemListagem] = []
    vistos: set[str] = set()

    # Varre todas as tabelas ou blocos de listagem na página de concursos
    for bloco in soup.select("div.bloco, table"):
        for link in bloco.select("a[href]"):
            titulo = colapsar_espacos(link.get_text(" "))
            href = str(link["href"])

            if not titulo or len(titulo) < 5 or _TITULOS_IGNORADOS.search(titulo):
                continue

            # Resolve URLs relativas ou absolutas
            url = canonizar(href if href.startswith("http") else urljoin(BASE, href))

            if url in vistos:
                continue
            vistos.add(url)

            # Tenta identificar o status com base no contexto ou texto descritivo próximo
            encerrado = False
            situacao = "Em andamento / Aberto"

            # Procura elemento de descrição vizinho (.resumoDesc)
            tr = link.find_parent("tr")
            if tr:
                resumo_elem = tr.select_one(".resumoDesc")
                if resumo_elem:
                    resumo_texto = resumo_elem.get_text(" ", strip=True)
                    situacao = resumo_texto
                    if "encerrada" in resumo_texto.lower():
                        encerrado = True

            itens.append(ItemListagem(titulo=titulo, url=url, encerrado=encerrado, situacao_site=situacao))

    return PaginaListagem(tuple(itens))


def parse_concurso(html: str, url: str, encerrado: bool = False, situacao_site: str | None = None) -> dict:
    """Extrai dados detalhados da página do concurso ou do portal de seleções."""
    soup = BeautifulSoup(html, "lxml")

    # Tenta extrair o título principal
    titulo_tag = soup.find("h1") or soup.find("h2") or soup.select_one(".tit")

    # Extrai o corpo/descrição principal da página
    corpo = soup.find("main") or soup.select_one("#centro") or soup.body

    arquivos = []
    # Varre links para editais em PDF ou arquivos anexos
    for a in soup.select("a[href]"):
        href = str(a["href"])
        texto_link = colapsar_espacos(a.get_text(" "))
        if ".pdf" in href.lower() or "edital" in href.lower() or "arquivo" in href.lower():
            arquivos.append(
                {
                    "titulo": texto_link or "Edital / Documento",
                    "url": urljoin(url, href),
                    "data": None,
                }
            )

    return {
        "fonte": "consulpam",
        "titulo": colapsar_espacos(titulo_tag.get_text(" ")) if titulo_tag else None,
        "situacao_site": situacao_site,
        "descricao": colapsar_espacos(corpo.get_text(" "))[:MAX_DESCRICAO] if corpo else None,
        "link_inscricao": url if "selecao.net.br" in url else None,
        "arquivos": arquivos,
        "encerrado": encerrado,
    }


def canonizar(url: str) -> str:
    partes = urlsplit(url)
    return f"{partes.scheme}://{partes.netloc.lower()}{partes.path.rstrip('/')}"


class FonteConsulpam:
    nome = "consulpam"
    dominios = frozenset({"consulpam.com.br", "selecao.net.br"})

    def descobrir(self, http: ClienteHttp, pular: frozenset[str] = frozenset()) -> ResultadoDescoberta:
        try:
            html_listagem = http.obter_texto(LISTAGEM)
        except ErroHttp as erro:
            log.error("Consulpam: falha ao acessar a listagem principal: %s", erro)
            return ResultadoDescoberta((), (f"{LISTAGEM}: {erro}",))

        listagem = parse_listagem(html_listagem)
        itens = [item for item in listagem.itens if item.url not in pular]

        log.info(
            "Consulpam: %d concursos encontrados no total; %d novos para processar.",
            len(listagem.itens),
            len(itens),
        )

        sinais: list[SinalDescoberta] = []
        falhas: list[str] = []

        for numero, item in enumerate(itens, start=1):
            if numero % 25 == 0:
                log.info("Consulpam: %d/%d páginas lidas", numero, len(itens))

            try:
                html_detalhe = http.obter_texto(item.url)
                payload = parse_concurso(
                    html_detalhe, item.url, encerrado=item.encerrado, situacao_site=item.situacao_site
                )
            except ErroHttp as erro:
                log.warning("Consulpam: falha ao ler %s: %s", item.url, erro)
                falhas.append(f"{item.url}: {erro}")
                continue

            sinais.append(
                SinalDescoberta(
                    titulo=payload["titulo"] or item.titulo,
                    url=item.url,
                    data_publicacao=None,
                    payload=payload,
                )
            )

        return ResultadoDescoberta(tuple(sinais), tuple(falhas))
