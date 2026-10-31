from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import requests
from bs4 import BeautifulSoup

from coletor.extratores.base import CargoExtraido, EditalExtraido
from coletor.extratores.secoes import (
    atribuir_disciplinas,
    calendario,
    extrair_isencoes,
    quadros_de_disciplinas,
    redacao_por_cargo,
)
from coletor.texto import (
    colapsar_espacos,
    data_por_extenso,
    normalizar,
    titulo_portugues,
    todas_as_datas,
    valores_monetarios,
)

BASE = "https://www.cesgranrio.org.br"
LISTAGEM = f"{BASE}/concursos?id=index-205112&ucat=27"

_NUMERO_EDITAL = re.compile(r"EDITAL\s+N\s*[º°o.]*\s*(\d{1,4})(?:\s*/\s*|\s*-\s*)(\d{4})", re.IGNORECASE)
_ORGAO_CABECALHO = (
    re.compile(
        r"CONCURSO P[ÚU]BLICO\s+PARA\s+"
        r"(?:A\s+SELE[ÇC][ÃA]O\s+DE\s+PESSOAL\s+DO|PROVIMENTO\s+DE\s+VAGAS\s+D[OA])\s+(.+)",
        re.IGNORECASE,
    ),
    re.compile(r"SELE[ÇC][ÃA]O\s+P[ÚU]BLICA\s+D[OA]\s+(.+)", re.IGNORECASE),
)

_VALOR_MONETARIO = r"R\$\s*\d{1,3}(?:\.\d{3})*,\d{2}"
_ESCOLARIDADE_MAP = {
    "superior": "SUPERIOR",
    "medio": "MEDIO",
    "tecnico": "TECNICO",
    "fundamental": "FUNDAMENTAL",
}


def listar_concursos(sessao: requests.Session, max_paginas: int = 5) -> list[dict]:
    """
    Varre as páginas de listagem de concursos abertos da Cesgranrio,
    mapeando os cards estruturados (.tmb) e controlando a paginação.
    """
    concursos = []
    urls_visitadas = set()
    url_atual = LISTAGEM

    pagina = 1
    while url_atual and pagina <= max_paginas:
        if url_atual in urls_visitadas:
            break
        urls_visitadas.add(url_atual)

        try:
            resp = sessao.get(url_atual, timeout=20)
            if not resp.ok:
                break

            soup = BeautifulSoup(resp.text, "lxml")
            cards = soup.select(".tmb")
            if not cards:
                break

            encontrou_novos = False
            for card in cards:
                link_elem = card.select_one("h3.t-entry-title a")
                if not link_elem:
                    continue

                titulo = link_elem.get_text(strip=True)
                link = link_elem.get("href")
                if link and not link.startswith("http"):
                    link = BASE + link

                categorias = [cat.get_text(strip=True) for cat in card.select(".t-entry-category a")]

                resumo_elem = card.select_one(".t-entry-excerpt p")
                resumo = resumo_elem.get_text(strip=True) if resumo_elem else ""

                item = {
                    "titulo": titulo,
                    "url": link,
                    "categorias": categorias,
                    "resumo": resumo,
                }
                if item not in concursos:
                    concursos.append(item)
                    encontrou_novos = True

            if not encontrou_novos:
                break

            # Avança para a próxima página de paginação
            pagina += 1
            proxima_link = soup.select_one(f"a.page-numbers:-soup-contains('{pagina}')")
            if not proxima_link:
                url_atual = f"{BASE}/concursos/page/{pagina}/?id=index-205112&ucat=27"
            else:
                url_atual = proxima_link.get("href")
                if url_atual and not url_atual.startswith("http"):
                    url_atual = BASE + url_atual

        except Exception:
            break

    return concursos


class ExtratorCesgranrio:
    def extrair(self, texto: str) -> EditalExtraido:
        avisos: list[str] = []

        numero, ano = self._numero_edital(texto)
        if numero is None:
            avisos.append("número do edital não encontrado")

        orgao = self._orgao(texto)

        cargos = self._cargos(texto)
        if not cargos:
            avisos.append("quadro de cargos/vagas não encontrado: confira o edital")

        inicio, fim = self._periodo_inscricao(texto)
        if inicio is None or fim is None:
            avisos.append("período de inscrição não encontrado")

        isencoes = extrair_isencoes(texto)

        prova = self._data_prova(texto)
        eventos = calendario(texto, isencoes, (inicio, fim), prova)
        if prova is None:
            prova = next((e.inicio for e in eventos if e.evento.startswith("Prova objetiva")), None)
        if prova is None:
            avisos.append("data da prova não encontrada")

        taxas = self._taxas(texto)
        if not taxas:
            avisos.append("taxa de inscrição não encontrada")

        avisos.extend(isencoes.avisos)

        cargos, faltou_quadro = atribuir_disciplinas(cargos, quadros_de_disciplinas(texto))
        if faltou_quadro:
            avisos.append("disciplinas de algum cargo não identificadas: confira o edital")

        cargos, redacao_incerta = redacao_por_cargo(texto, cargos)
        if redacao_incerta:
            avisos.append("prova discursiva/redação por cargo não identificada: confira o edital")

        return EditalExtraido(
            orgao=orgao,
            numero_edital=numero,
            ano=ano,
            cargos=tuple(cargos),
            inscricao_inicio=inicio,
            inscricao_fim=fim,
            data_prova=prova,
            taxa_min=min(taxas) if taxas else None,
            taxa_max=max(taxas) if taxas else None,
            isencoes=isencoes.tipos,
            isencao_inicio=isencoes.inicio,
            isencao_fim=isencoes.fim,
            eventos=eventos,
            avisos=tuple(avisos),
        )

    @staticmethod
    def _numero_edital(texto: str) -> tuple[str | None, int | None]:
        m = _NUMERO_EDITAL.search(texto[:5000])
        if m is None:
            return None, None
        return f"{int(m.group(1)):02d}/{m.group(2)}", int(m.group(2))

    @staticmethod
    def _orgao(texto: str) -> str | None:
        cabecalho = colapsar_espacos(texto[:2000])
        for padrao in _ORGAO_CABECALHO:
            if m := padrao.search(cabecalho):
                nome = m.group(1).split("-")[0].split(".")[0]
                return titulo_portugues(nome.strip(" -–,"))
        return None

    @staticmethod
    def _cargos(texto: str) -> list[CargoExtraido]:
        cargos: list[CargoExtraido] = []
        padrao_cargo = re.compile(
            r"CARGO\s*\d*\s*[:–-]\s*(?P<nome>[^\n–-]+)(?:\s*[-–]\s*(?P<esp>[^\n]+))?",
            re.IGNORECASE,
        )

        for m in padrao_cargo.finditer(texto):
            nome = titulo_portugues(m.group("nome").strip())
            especialidade = titulo_portugues(m.group("esp").strip()) if m.group("esp") else None
            if len(nome) < 3 or "conforme" in nome.lower():
                continue

            cargos.append(
                CargoExtraido(
                    nome=nome,
                    especialidade=especialidade,
                )
            )

        vistos = set()
        cargos_unicos = []
        for c in cargos:
            chave = (c.nome.lower(), (c.especialidade or "").lower())
            if chave not in vistos:
                vistos.add(chave)
                cargos_unicos.append(c)

        return cargos_unicos

    @staticmethod
    def _periodo_inscricao(texto: str) -> tuple[date | None, date | None]:
        normal = normalizar(texto)
        for m in re.finditer(r"inscric(?:ao|oes)", normal):
            janela = normal[m.start() : m.start() + 350]
            if "periodo" in janela or "a partir" in janela or "das" in janela:
                datas = todas_as_datas(janela)
                if len(datas) >= 2:
                    return datas[0], datas[1]
        return None, None

    @staticmethod
    def _data_prova(texto: str) -> date | None:
        normal = normalizar(texto)
        if m := re.search(r"provas?\s+objetivas?\s+ser(?:a|ao)\s+aplicadas?\s+em\s+([^.;\n]{1,60})", normal):
            return data_por_extenso(m.group(1))
        return None

    @staticmethod
    def _taxas(texto: str) -> list[Decimal]:
        valores: set[Decimal] = set()
        for m in re.finditer(r"valor\s+da\s+taxa\s+de\s+inscricao", texto, re.IGNORECASE):
            janela = texto[m.start() : m.start() + 200]
            valores.update(v for v in valores_monetarios(janela) if Decimal(0) < v < Decimal(2000))
        return sorted(valores)
