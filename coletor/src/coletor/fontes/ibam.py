"""Fonte IBAM (Instituto Brasileiro de Administração Municipal): https://www.ibam-concursos.org.br.

Estrutura observada em 29/10/2026 (ASP clássico): uma única página `default.asp?status=2` ("em andamento",
que inclui os de edital disponível) com um `div.card` por concurso: título em `h4`, descrição, avisos de
inscrição/prova, situação em `strong.status`, quadro de cargos por escolaridade (`#cargos-<id>`: código | nome,
data da prova, vagas ou CR, vagas PcD, taxa) e documentos (`#docs-<id>`). Não há página de detalhe.
robots.txt: inexistente (404) em 29/10/2026. Concursos de SP ficam em outro site (ibamsp-concursos), fora daqui.
"""

from __future__ import annotations

import contextlib
import logging
import re
from datetime import date
from decimal import Decimal
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from coletor.extratores.base import CargoExtraido
from coletor.fontes.base import DadosEstruturados, ResultadoDescoberta, SinalDescoberta
from coletor.http_cliente import ClienteHttp, ErroHttp
from coletor.texto import (
    MESES,
    UFS,
    colapsar_espacos,
    escolaridade_por_texto,
    normalizar,
    titulo_portugues,
    valor_monetario,
)

log = logging.getLogger(__name__)

BASE = "https://www.ibam-concursos.org.br/"
LISTAGEM = f"{BASE}default.asp?status=2"

# "Prefeitura de Lages/SC - Ed. 03/2026 - PS", "Municipio de Serra Alta/SC - CP 01", "AMTTC/PE - Ed. 01/2024 - CP"
_TITULO = re.compile(r"^(?P<orgao>.+?)\s*/\s*(?P<uf>[A-Z]{2})\b(?P<resto>.*)$")
_NUMERO_EDITAL = re.compile(r"(?:Ed\.?|Edital|PS|CP|PSP)\s*(?:n[ºo°.]*\s*)?(\d{1,3})\s*/\s*(\d{2,4})", re.IGNORECASE)
_DATA_COMPLETA = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_INSCRICOES = re.compile(r"inscric(?:ao|oes)\s*:?(?P<trecho>[^.]*?\d{4})", re.IGNORECASE)
_SITUACOES = {
    "edital disponivel": "INSCRICOES_ABERTAS",
    "inscricoes abertas": "INSCRICOES_ABERTAS",
    "concurso suspenso": "ENCERRADO",
    "resultado final": "ENCERRADO",
    "homologacao": "ENCERRADO",
}
_ORGAO_MUNICIPAL = re.compile(r"^(prefeitura|municipio|camara|fundacao municipal|instituto|ipc|amttc)", re.IGNORECASE)
_MUNICIPIO = re.compile(r"^(?:prefeitura|munic[ií]pio|c[aâ]mara)(?:\s+municipal)?\s+d[eoa]s?\s+(.+)$", re.IGNORECASE)


def parse_listagem(html: str) -> list[SinalDescoberta]:
    soup = BeautifulSoup(html, "lxml")
    sinais = []
    for colapso in soup.find_all(id=re.compile(r"^collapse-\d+$")):
        cartao = colapso.find_parent("div", class_="card")
        if cartao is None:
            continue
        codigo = colapso["id"].split("-", 1)[1]
        sinais.append(_parse_cartao(cartao, codigo))
    if not sinais and soup.find("h4") is None:
        raise ErroHttp("listagem do IBAM sem concursos nem títulos (o layout do site mudou?)")
    return sinais


def _parse_cartao(cartao: Tag, codigo: str) -> SinalDescoberta:
    titulo = colapsar_espacos(cartao.find("h4").get_text(" ")) if cartao.find("h4") else f"Concurso IBAM {codigo}"
    descricao_tag = cartao.select_one(".fs-16")
    avisos_tag = cartao.select_one("span.text-danger")
    status_tag = cartao.select_one("strong.status")
    situacao_site = colapsar_espacos(status_tag.get_text(" ")) if status_tag else None
    texto_avisos = colapsar_espacos(avisos_tag.get_text(" ")) if avisos_tag else ""

    cargos, taxas, datas_prova = _cargos(cartao, codigo)
    inicio, fim = _periodo_inscricao(texto_avisos)
    prova = _data_prevista(cartao) or (min(datas_prova) if datas_prova else None)
    orgao, uf, municipio, esfera = _orgao(titulo)
    numero = _NUMERO_EDITAL.search(titulo)
    ano = None
    if numero:
        ano = int(numero.group(2)) if len(numero.group(2)) == 4 else 2000 + int(numero.group(2))

    avisos = []
    if fim is None and _SITUACOES.get(normalizar(situacao_site or "")) == "INSCRICOES_ABERTAS":
        avisos.append("prazo de inscrição não identificado na página: confira o edital")
    if cargos and all(c.salario is None for c in cargos):
        avisos.append("salários só no edital (Anexo I)")

    arquivos = []
    for link in cartao.select(f"#docs-{codigo} a[href]"):
        url = urljoin(BASE, str(link["href"]))
        arquivos.append(
            {
                "titulo": colapsar_espacos(link.get_text(" ")),
                "url": url,
                "data": None,
                "pdf": url.lower().endswith(".pdf"),
            }
        )

    url_sinal = f"{LISTAGEM}#cargos-{codigo}"
    estruturado = DadosEstruturados(
        orgao=orgao,
        esfera=esfera,
        uf=uf,
        municipio=municipio,
        numero_edital=f"{int(numero.group(1)):02d}/{ano}" if numero and ano else None,
        ano=ano,
        situacao=_SITUACOES.get(normalizar(situacao_site or ""), "EM_ANDAMENTO"),
        inscricao_inicio=inicio,
        inscricao_fim=fim,
        data_prova=prova,
        taxa_min=min(taxas) if taxas else None,
        taxa_max=max(taxas) if taxas else None,
        cargos=tuple(cargos),
        avisos=tuple(avisos),
    )
    payload = {
        "fonte": "ibam",
        "titulo": titulo,
        "situacao_site": situacao_site,
        "descricao": colapsar_espacos(f"{descricao_tag.get_text(' ') if descricao_tag else ''} {texto_avisos}"),
        "link_inscricao": url_sinal if estruturado.situacao == "INSCRICOES_ABERTAS" else None,
        "arquivos": arquivos,
    }
    return SinalDescoberta(titulo=titulo, url=url_sinal, payload=payload, estruturado=estruturado)


def _cargos(cartao: Tag, codigo: str) -> tuple[list[CargoExtraido], list[Decimal], list[date]]:
    cargos: list[CargoExtraido] = []
    taxas: list[Decimal] = []
    datas: list[date] = []
    bloco = cartao.find(id=f"cargos-{codigo}")
    if bloco is None:
        return cargos, taxas, datas
    escolaridade = None
    for elemento in bloco.find_all(["h5", "tr"]):
        if elemento.name == "h5":
            escolaridade = escolaridade_por_texto(elemento.get_text(" "))
            continue
        celulas = [colapsar_espacos(td.get_text(" ")) for td in elemento.find_all("td")]
        if len(celulas) < 5:
            continue
        nome = titulo_portugues(re.sub(r"^\d+\s*\|\s*", "", celulas[0]))
        vagas_texto = celulas[2].upper()
        if (taxa := valor_monetario(celulas[4])) is not None:
            taxas.append(taxa)
        if (m := re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", celulas[1])) is not None:
            ano = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
            with contextlib.suppress(ValueError):
                datas.append(date(ano, int(m.group(2)), int(m.group(1))))
        cargos.append(
            CargoExtraido(
                nome=nome,
                escolaridade=escolaridade,
                vagas=int(vagas_texto) if vagas_texto.isdigit() else None,
                cadastro_reserva="CR" in vagas_texto,
            )
        )
    return cargos, taxas, datas


def _periodo_inscricao(texto: str) -> tuple[date | None, date | None]:
    """'das 06h do dia 21/10 às 18h do dia 16/11/2026' ou 'das 06h do dia 02 às 18h do dia 30 de outubro de 2026'.
    O início costuma vir sem ano (e às vezes sem mês): herda do fim."""
    m = _INSCRICOES.search(normalizar(texto))
    if m is None:
        return None, None
    trecho = m.group("trecho")
    fim = _ultima_data(trecho)
    if fim is None:
        return None, None
    inicio = None
    if (dm := re.search(r"dia (\d{1,2})(?:/(\d{1,2}))?", trecho)) is not None:
        mes = int(dm.group(2)) if dm.group(2) else fim.month
        ano = fim.year - 1 if mes > fim.month else fim.year
        try:
            inicio = date(ano, mes, int(dm.group(1)))
        except ValueError:
            inicio = None
    return (inicio if inicio and inicio <= fim else None), fim


def _ultima_data(trecho: str) -> date | None:
    candidatas: list[tuple[int, date]] = []
    for m in _DATA_COMPLETA.finditer(trecho):
        with contextlib.suppress(ValueError):
            candidatas.append((m.start(), date(int(m.group(3)), int(m.group(2)), int(m.group(1)))))
    for m in re.finditer(r"(\d{1,2}) de ([a-z]+) de (\d{4})", trecho):
        if (mes := MESES.get(m.group(2))) is not None:
            with contextlib.suppress(ValueError):
                candidatas.append((m.start(), date(int(m.group(3)), mes, int(m.group(1)))))
    return max(candidatas)[1] if candidatas else None


def _data_prevista(cartao: Tag) -> date | None:
    alvo = cartao.find(string=re.compile("Data prevista da prova"))
    if alvo is None or (m := _DATA_COMPLETA.search(alvo)) is None:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _orgao(titulo: str) -> tuple[str | None, str | None, str | None, str | None]:
    m = _TITULO.match(titulo)
    if m is None or m.group("uf") not in set(UFS.values()):
        return None, None, None, None
    nome = colapsar_espacos(m.group("orgao"))
    municipio = _MUNICIPIO.match(nome)
    esfera = "MUNICIPAL" if _ORGAO_MUNICIPAL.match(nome) else None
    return nome, m.group("uf"), municipio.group(1).strip() if municipio else None, esfera


class FonteIBAM:
    nome = "ibam"
    dominios = frozenset({"ibam-concursos.org.br"})

    def descobrir(self, http: ClienteHttp) -> ResultadoDescoberta:
        sinais = parse_listagem(http.obter_texto(LISTAGEM))
        log.info("IBAM: %d concursos na página 'em andamento'", len(sinais))
        return ResultadoDescoberta(tuple(sinais))
