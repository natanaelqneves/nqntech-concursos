"""Fonte IBADE (Instituto Brasileiro de Apoio e Desenvolvimento Executivo): https://portal.ibade.selecao.site.

Estrutura observada em 29/10/2026 (plataforma "Gestor Editais"): a listagem `/edital` tem abas
`#abertos`, `#andamento`, `#futuros` e `#encerrados` com um cartão por concurso (tipo e número, órgão e link
`/edital/ver/<id>`). A página do concurso traz `#arquivos` (data, título, link de download em
ibade.selecao.site/arquivo.php) e `#vagas` (cargos agrupados por escolaridade, com código e requisitos).
Datas, vagas e salários só existem no PDF do edital. robots.txt: inexistente (404) em 29/10/2026.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from coletor.extratores.base import CargoExtraido
from coletor.fontes.base import DadosEstruturados, ResultadoDescoberta, SinalDescoberta
from coletor.http_cliente import ClienteHttp, ErroHttp
from coletor.texto import colapsar_espacos, escolaridade_por_texto, titulo_portugues, uf_por_nome

log = logging.getLogger(__name__)

LISTAGEM = "https://portal.ibade.selecao.site/edital"
ABAS = {"abertos": "INSCRICOES_ABERTAS", "andamento": "EM_ANDAMENTO", "futuros": "PREVISTO"}
_NUMERO = re.compile(r"(\d{1,4})\s*/\s*(\d{4})")
_UF_SIGLA = re.compile(r"[/\s-]([A-Z]{2})\s*$")
AVISO_SEM_DETALHES = "vagas, salários e datas só no edital: confira o PDF"


def parse_listagem(html: str) -> list[tuple[str, str, str]]:
    """(url, título, situação) dos concursos das abas de interesse; encerrados ficam de fora."""
    soup = BeautifulSoup(html, "lxml")
    abas = {aba.get("id"): aba for aba in soup.select(".tab-pane[id]")}
    if not abas:
        raise ErroHttp("listagem do IBADE sem as abas de concursos (o layout do site mudou?)")
    itens = []
    for nome_aba, situacao in ABAS.items():
        aba = abas.get(nome_aba)
        if aba is None:
            continue
        for cartao in aba.select(".card"):
            link = cartao.select_one("a.detalhes-edital[href]")
            if link is None:
                continue
            textos = [colapsar_espacos(p.get_text(" ")) for p in cartao.select("p")]
            itens.append((str(link["href"]).split("#")[0], " - ".join(t for t in textos if t), situacao))
    return itens


def parse_edital(html: str, url: str, situacao: str) -> SinalDescoberta:
    soup = BeautifulSoup(html, "lxml")
    cabecalho = soup.select_one("p.text-16") or soup.find("u")
    linhas = [colapsar_espacos(t) for t in cabecalho.stripped_strings] if cabecalho else []
    tipo_numero = linhas[0] if linhas else ""
    orgao_original = linhas[1] if len(linhas) > 1 else ""
    orgao = titulo_portugues(orgao_original) if orgao_original else None
    titulo = colapsar_espacos(f"{tipo_numero} - {orgao}") if orgao else tipo_numero or url

    arquivos = []
    for item in soup.select("#arquivos .list-group-item"):
        link = item.select_one("a[href]")
        nome = item.select_one("p")
        data = item.select_one("small")
        if link is None or nome is None:
            continue
        href = str(link["href"])
        arquivos.append(
            {
                "titulo": colapsar_espacos(nome.get_text(" ")),
                "url": href,
                "data": _data_iso(data.get_text(strip=True) if data else ""),
                # O download passa por arquivo.php?file=...pdf: a extensão está no parâmetro, não no caminho.
                "pdf": href.lower().split("#")[0].endswith(".pdf"),
            }
        )

    numero = _NUMERO.search(tipo_numero)
    uf = _uf(orgao_original)
    estruturado = DadosEstruturados(
        orgao=orgao,
        uf=uf,
        numero_edital=f"{int(numero.group(1)):02d}/{numero.group(2)}" if numero else None,
        ano=int(numero.group(2)) if numero else None,
        situacao=situacao,
        cargos=tuple(_cargos(soup)),
        avisos=(AVISO_SEM_DETALHES,),
    )
    payload = {
        "fonte": "ibade",
        "titulo": titulo,
        "situacao_site": situacao,
        "descricao": colapsar_espacos(" ".join(c.descricao() for c in _cargos_textos(soup))),
        "link_inscricao": url if situacao == "INSCRICOES_ABERTAS" else None,
        "arquivos": arquivos,
    }
    datas = [a["data"] for a in arquivos if a["data"]]
    return SinalDescoberta(
        titulo=titulo,
        url=url,
        payload=payload,
        estruturado=estruturado,
        data_publicacao=datetime.fromisoformat(max(datas)).date() if datas else None,
    )


class _CargoTexto:
    def __init__(self, nome: str, requisitos: str) -> None:
        self.nome = nome
        self.requisitos = requisitos

    def descricao(self) -> str:
        return f"{self.nome}: {self.requisitos}" if self.requisitos else self.nome


def _cargos_textos(soup: BeautifulSoup) -> list[_CargoTexto]:
    textos = []
    for item in soup.select("#vagas .list-group-item"):
        nome = item.select_one("p span") or item.select_one("p")
        requisitos = item.select_one(".alert-observacao p")
        if nome is not None:
            textos.append(
                _CargoTexto(
                    colapsar_espacos(nome.get_text(" ")),
                    colapsar_espacos(requisitos.get_text(" ")) if requisitos else "",
                )
            )
    return textos


def _cargos(soup: BeautifulSoup) -> list[CargoExtraido]:
    cargos: dict[str, CargoExtraido] = {}
    for grupo in soup.select("#vagas .card"):
        cabecalho = grupo.select_one(".card-header")
        escolaridade = escolaridade_por_texto(cabecalho.get_text(" ") if cabecalho else "")
        for item in grupo.select(".list-group-item"):
            nome_tag = item.select_one("p span") or item.select_one("p")
            if nome_tag is None:
                continue
            # "S01 - ADVOGADO I" / "M01 - Prestador ... - Lotação: ARIQUEMES": o código e a lotação saem do nome.
            nome = re.sub(r"^[A-Z]{0,3}\d{1,3}\s*-\s*", "", colapsar_espacos(nome_tag.get_text(" ")))
            nome = re.split(r"\s+-\s+(?:lota[cç][aã]o|un)\s*:", nome, flags=re.IGNORECASE)[0]
            if re.match(r"^un\s*:", nome, flags=re.IGNORECASE):
                continue  # "UN: EMEF ... - TIPOLOGIA: D" é a unidade de lotação, não um cargo
            nome = titulo_portugues(nome.strip(" -"))
            cargos.setdefault(nome.lower(), CargoExtraido(nome=nome, escolaridade=escolaridade))
    return list(cargos.values())


def _uf(orgao: str) -> str | None:
    if (m := _UF_SIGLA.search(orgao)) is not None:
        return m.group(1)
    return uf_por_nome(orgao)


def _data_iso(texto: str) -> str | None:
    try:
        return datetime.strptime(texto.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


class FonteIBADE:
    nome = "ibade"
    dominios = frozenset({"portal.ibade.selecao.site", "ibade.selecao.site"})

    def descobrir(self, http: ClienteHttp) -> ResultadoDescoberta:
        itens = parse_listagem(http.obter_texto(LISTAGEM))
        log.info("IBADE: %d concursos em aberto, em andamento ou futuros", len(itens))
        sinais: list[SinalDescoberta] = []
        falhas: list[str] = []
        for url, titulo, situacao in itens:
            try:
                sinais.append(parse_edital(http.obter_texto(url), url, situacao))
            except ErroHttp as erro:
                log.warning("IBADE: falha ao ler %s (%s): %s", url, titulo, erro)
                falhas.append(f"{url}: {erro}")
        return ResultadoDescoberta(tuple(sinais), tuple(falhas))
