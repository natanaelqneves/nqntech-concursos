"""Fonte Cesgranrio: listagem de concursos em https://www.cesgranrio.org.br/concursos?id=index-205112&ucat=27.

Estrutura observada:
- listagem: blocos `.tmb` contendo título, link e metadados do concurso;
- paginação controlada por parâmetros de URL ou links `.page-numbers`;
- página do concurso: `h1`, descrições, links de inscrição e arquivos/editais.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from coletor.extratores.cesgranrio import ExtratorCesgranrio
from coletor.fontes.base import DadosEstruturados, ResultadoDescoberta, SinalDescoberta
from coletor.http_cliente import ClienteHttp, ErroHttp
from coletor.texto import colapsar_espacos, normalizar, uf_por_nome

log = logging.getLogger(__name__)

BASE = "https://www.cesgranrio.org.br"
LISTAGEM = f"{BASE}/concursos?id=index-205112&ucat=27"
MAX_DESCRICAO = 4000

_NUMERO = re.compile(r"(\d{1,4})\s*/\s*(\d{4})")
_UF_SIGLA = re.compile(r"[/\s-]([A-Z]{2})\s*$")


def parse_listagem(html: str) -> tuple[list[dict], int]:
    """Varre as páginas de listagem da Cesgranrio mapeando os cards (.tmb)."""
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select(".tmb")
    if not cards:
        raise ErroHttp("Listagem da Cesgranrio sem cards (.tmb) (o layout do site mudou?)")

    itens = []
    for card in cards:
        link_elem = card.select_one("h3.t-entry-title a")
        if not link_elem:
            continue

        titulo = colapsar_espacos(link_elem.get_text(" "))
        url = urljoin(BASE, str(link_elem["href"]))

        # Determina a situação com base nas categorias do card ou padrão aberto
        categorias = [colapsar_espacos(cat.get_text(" ")) for cat in card.select(".t-entry-category a")]
        cat_texto = " ".join(categorias).lower()

        if "encerrado" in cat_texto:
            situacao = "ENCERRADO"
        elif "inscrição" in cat_texto or "aberto" in cat_texto:
            situacao = "INSCRICOES_ABERTAS"
        else:
            situacao = "EM_ANDAMENTO"

        resumo_elem = card.select_one(".t-entry-excerpt p")
        resumo = colapsar_espacos(resumo_elem.get_text(" ")) if resumo_elem else ""

        itens.append(
            {
                "titulo": titulo,
                "url": url,
                "situacao": situacao,
                "resumo": resumo,
            }
        )

    # Identifica o número máximo de páginas na paginação se houver
    paginas = [1]
    for p_link in soup.select("a.page-numbers"):
        texto = p_link.get_text(strip=True)
        if texto.isdigit():
            paginas.append(int(texto))

    return itens, max(paginas)


def parse_concurso(html: str, url: str, situacao_padrao: str = "EM_ANDAMENTO") -> dict:
    """Extrai os dados detalhados da página do concurso da Cesgranrio."""
    soup = BeautifulSoup(html, "lxml")
    principal = soup.find("main") or soup
    titulo_tag = principal.find("h1")

    corpo = principal.select_one(".post-content") or principal.select_one(".entry-content") or principal

    arquivos = []
    for link in principal.select("a[href]"):
        href = str(link["href"])
        texto_link = colapsar_espacos(link.get_text(" "))
        if href.lower().endswith(".pdf") or "edital" in href.lower() or "arquivo" in href.lower():
            if not href.startswith("http"):
                href = urljoin(BASE, href)
            arquivos.append(
                {
                    "titulo": texto_link or "Documento",
                    "url": href,
                    "data": None,
                    "pdf": href.lower().endswith(".pdf"),
                }
            )

    titulo = colapsar_espacos(titulo_tag.get_text(" ")) if titulo_tag else url

    return {
        "fonte": "cesgranrio",
        "titulo": titulo,
        "situacao_site": situacao_padrao,
        "descricao": colapsar_espacos(corpo.get_text(" "))[:MAX_DESCRICAO] if corpo else None,
        "link_inscricao": _link_inscricao(principal),
        "arquivos": arquivos,
    }


def _link_inscricao(principal: Tag) -> str | None:
    for link in principal.select("a[href]"):
        texto = normalizar(link.get_text(" "))
        href = str(link["href"])
        if "inscric" in texto or "portal" in texto or "login" in texto or "candidato" in texto:
            return urljoin(BASE, href)
    return None


class FonteCESGRANRIO:
    nome = "cesgranrio"
    dominios = frozenset({"cesgranrio.org.br", "www.cesgranrio.org.br"})

    def __init__(self, max_paginas: int = 15, max_paginas_realizados: int = 0):
        self.max_paginas = max_paginas
        self.max_paginas_realizados = max_paginas_realizados

    def descobrir(self, http: ClienteHttp, pular: frozenset[str] = frozenset()) -> ResultadoDescoberta:
        listados = self._listar(http)
        itens = [item for item in listados if item["url"] not in pular]

        log.info(
            "Cesgranrio: %d concursos encontrados (%d novos/não lidos)",
            len(listados),
            len(itens),
        )

        sinais: list[SinalDescoberta] = []
        falhas: list[str] = []

        extrator_edital = ExtratorCesgranrio()

        for item in itens:
            url = item["url"]
            try:
                html = http.obter_texto(url)
                payload = parse_concurso(html, url, item["situacao"])

                # Executa o extrator estruturado no texto da página/editais se disponível
                estruturado = None
                try:
                    edital_extraido = extrator_edital.extrair(payload["descricao"] or "")
                    estruturado = DadosEstruturados(
                        orgao=edital_extraido.orgao,
                        uf=uf_por_nome(edital_extraido.orgao or ""),
                        numero_edital=edital_extraido.numero_edital,
                        ano=edital_extraido.ano,
                        situacao=item["situacao"],
                        cargos=edital_extraido.cargos,
                        avisos=edital_extraido.avisos,
                    )
                except Exception:
                    pass

                sinais.append(
                    SinalDescoberta(
                        titulo=payload["titulo"] or item["titulo"],
                        url=url,
                        payload=payload,
                        estruturado=estruturado,
                    )
                )
            except ErroHttp as erro:
                log.warning("Cesgranrio: falha ao ler %s: %s", url, erro)
                falhas.append(f"{url}: {erro}")

        return ResultadoDescoberta(tuple(sinais), tuple(falhas))

    def _listar(self, http: ClienteHttp) -> list[dict]:
        concursos = []
        url_atual = LISTAGEM
        pagina = 1

        while url_atual and pagina <= self.max_paginas:
            try:
                html = http.obter_texto(url_atual)
                itens, ultima_pag = parse_listagem(html)

                for item in itens:
                    if item not in concursos:
                        concursos.append(item)

                if pagina >= self.max_paginas or pagina >= ultima_pag:
                    break

                pagina += 1
                url_atual = f"{BASE}/concursos/page/{pagina}/?id=index-205112&ucat=27"
            except Exception:
                break

        return concursos
