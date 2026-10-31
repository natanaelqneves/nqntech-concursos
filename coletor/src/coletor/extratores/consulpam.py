"""Extrator por regras para editais da Consulpam.

Baseado no layout da Consulpam (ex: Prefeitura de São João do Piauí-PI, Edital 003/2026)
e nos padrões de títulos e resumos das listagens da banca.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

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

_NUMERO_EDITAL = re.compile(r"EDITAL\s*N?[º°o.]*\s*(\d{1,4})\s*/\s*(\d{4})", re.IGNORECASE)
_TAXA_MAXIMA_PLAUSIVEL = Decimal("2000")


@dataclass
class ExtratorConsulpam:
    """Extrator especializado em editais e páginas de concursos da Consulpam."""

    def extrair(self, html_ou_texto: str) -> EditalExtraido:
        avisos: list[str] = []

        # Suporte a BeautifulSoup ou texto puro
        if "<html" in html_ou_texto.lower() or "<div" in html_ou_texto.lower():
            soup = BeautifulSoup(html_ou_texto, "html.parser")
            texto = soup.get_text(separator="\n")
        else:
            texto = html_ou_texto

        numero, ano = self._numero_edital(texto)
        if numero is None:
            avisos.append("número do edital não encontrado")

        orgao = self._orgao(texto)
        if orgao is None:
            avisos.append("órgão não encontrado")

        cargos = self._cargos(texto)
        if not cargos:
            avisos.append("quadro de cargos/vagas não encontrado: confira o edital")

        inicio, fim = self._periodo_inscricao(texto)
        if inicio is None or fim is None:
            avisos.append("período de inscrição não encontrado")
        elif fim < inicio:
            avisos.append("período de inscrição incoerente (fim antes do início): confira o edital")
            inicio = fim = None

        isencoes = extrair_isencoes(texto)
        prova = self._data_prova(texto)
        eventos = calendario(texto, isencoes, (inicio, fim), prova)
        if prova is None:
            prova = next((e.inicio for e in eventos if e.evento.startswith("Prova objetiva")), None)
        if prova is None:
            avisos.append("data da prova não encontrada")
        elif fim is not None and prova < fim:
            avisos.append("data da prova anterior ao fim das inscrições: confira o edital")

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
        m = _NUMERO_EDITAL.search(texto[:8000])
        if m is None:
            return None, None
        return f"{int(m.group(1)):02d}/{m.group(2)}", int(m.group(2))

    @staticmethod
    def _orgao(texto: str) -> str | None:
        # Exemplo padrão Consulpam nos títulos: "PREFEITURA MUNICIPAL DE SÃO JOÃO DO PIAUÍ-PI"
        m = re.search(
            r"(PREFEITURA MUNICIPAL DE [^\n(]+|CÂMARA MUNICIPAL DE [^\n(]+|[A-ZÃÉÍÓÚÂÊÔÃÕÇ\s-]+)", texto, re.IGNORECASE
        )
        if m:
            orgao_limpo = colapsar_espacos(m.group(1)).strip(" -–")
            if len(orgao_limpo) > 3:
                return titulo_portugues(orgao_limpo)
        return None

    @staticmethod
    def _cargos(texto: str) -> list[CargoExtraido]:
        cargos: list[CargoExtraido] = []
        # Procura por menções a cargos ou linhas descritivas no edital
        for linha in texto.split("\n"):
            linha_limpa = linha.strip()
            if ("cargo" in linha_limpa.lower() or "função" in linha_limpa.lower()) and len(
                linha_limpan := titulo_portugues(linha_limpa)
            ) < 100:
                cargos.append(CargoExtraido(nome=linha_limpan))
        return cargos[:20]  # Limita para evitar falsos positivos excessivos caso o texto seja longo

    @staticmethod
    def _periodo_inscricao(texto: str) -> tuple[date | None, date | None]:
        normal = normalizar(texto)
        for m in re.finditer(r"inscric(?:ao|oes)", normal):
            janela = normal[m.start() : m.start() + 300]
            datas = todas_as_datas(janela)
            if len(datas) >= 2:
                return datas[0], datas[1]
        return None, None

    @staticmethod
    def _data_prova(texto: str) -> date | None:
        normal = normalizar(texto)
        for m in re.finditer(r"provas?\b[^.]{0,500}?(?:no dia|na data de|em)\s+([^.;]{0,60})", normal):
            trecho = m.group(1)
            if (achada := data_por_extenso(trecho)) is not None:
                return achada
        return None

    @staticmethod
    def _taxas(texto: str) -> list[Decimal]:
        valores: set[Decimal] = set()
        for m in re.finditer(r"(?:valor d[ae] |taxa de )inscri", texto, re.IGNORECASE):
            janela = texto[m.start() : m.start() + 220]
            valores.update(v for v in valores_monetarios(janela) if Decimal(0) < v < _TAXA_MAXIMA_PLAUSIVEL)
        return sorted(valores)
