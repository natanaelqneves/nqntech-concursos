"""Recorte geográfico do concurso: abrangência (NACIONAL/ESTADUAL/MUNICIPAL), UF e município do IBGE.

Regras (seção 4.6 do contexto):
- CNU e órgãos federais sem local definido → NACIONAL (aparecem em qualquer recorte do site);
- órgãos federais de um só estado (TRT da 13ª Região, universidades e institutos federais com o estado no
  nome) → ESTADUAL, porque as vagas são daquele estado;
- estaduais → ESTADUAL com a UF; municipais → MUNICIPAL com o código IBGE do município.
Sem informação suficiente, a abrangência fica vazia (o concurso não é publicado) e sai um aviso legível.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from coletor.classificacao.orgao import SIGLAS_UF, OrgaoInferido
from coletor.texto import UFS, normalizar, slugificar

# TRTs de um estado só (os da 8ª, 10ª, 11ª e 14ª Regiões abrangem dois estados e ficam nacionais).
_TRT_UF = {
    1: "RJ", 2: "SP", 3: "MG", 4: "RS", 5: "BA", 6: "PE", 7: "CE", 9: "PR", 12: "SC", 13: "PB", 15: "SP",
    16: "MA", 17: "ES", 18: "GO", 19: "AL", 20: "SE", 21: "RN", 22: "PI", 23: "MT", 24: "MS",
}  # fmt: skip
_TRT_REGIAO = re.compile(r"\b(?:trabalho|trt) da (\d{1,2}) ?a? regiao\b")
# TRFs: só o da 6ª Região (Minas Gerais) tem um estado só.
_TRF_UF = {6: "MG"}
_TRF_REGIAO = re.compile(r"\b(?:tribunal regional federal|trf) da (\d) ?a? regiao\b")
# Nome do município colado na UF ("IPC - Arraial do Cabo/RJ") ou no fim do nome do órgão
# ("Secretaria Municipal de Fazenda de Cuiabá"): candidatos conferidos contra a lista do IBGE.
_ANTES_DA_BARRA = re.compile(r"([^/–-]+?)\s*/\s*[A-Z]{2}\b")
_PREPOSICAO = re.compile(r"\s+d[eoa]s?\s+")
# Assuntos de secretaria que também são nomes de município ("Saúde", na Bahia): nunca valem como município.
_ASSUNTOS = frozenset(
    {"saude", "educacao", "fazenda", "cultura", "esporte", "esportes", "turismo", "agricultura", "obras",
     "planejamento", "administracao", "transito", "seguranca", "justica", "habitacao", "trabalho", "juventude",
     "comunicacao", "assistencia social", "meio ambiente", "financas", "governo", "gestao"}
)  # fmt: skip
# Capitais: desempate quando o nome do município existe em mais de um estado (Belém, Rio Branco...).
CAPITAIS = frozenset({
    1100205, 1200401, 1302603, 1400100, 1501402, 1600303, 1721000, 2111300, 2211001, 2304400, 2408102, 2507507,
    2611606, 2704302, 2800308, 2927408, 3106200, 3205309, 3304557, 3550308, 4106902, 4205407, 4314902, 5002704,
    5103403, 5208707, 5300108,
})  # fmt: skip
_ESTADO_POR_EXTENSO = re.compile(
    r"\bestado d[eoa]s? (" + "|".join(sorted((re.escape(n) for n in UFS), key=len, reverse=True)) + r")\b"
)
# Só depois de barra ("Macaé/RJ"): " - AC" num edital costuma ser "ampla concorrência", não Acre.
_UF_APOS_BARRA = re.compile(r"/\s?([A-Z]{2})\b")


@dataclass(frozen=True)
class Municipio:
    codigo_ibge: int
    nome: str
    uf: str
    slug: str


@dataclass(frozen=True)
class Local:
    abrangencia: str | None
    uf: str | None = None
    municipio_ibge: int | None = None
    aviso: str | None = None


class IndiceMunicipios:
    def __init__(self, municipios: Iterable[Municipio]) -> None:
        self._por_slug: dict[str, list[Municipio]] = defaultdict(list)
        for municipio in municipios:
            self._por_slug[municipio.slug].append(municipio)

    def __len__(self) -> int:
        return sum(len(m) for m in self._por_slug.values())

    def buscar(self, nome: str, uf: str | None = None) -> list[Municipio]:
        candidatos = self._por_slug.get(slugificar(nome), [])
        return [m for m in candidatos if m.uf == uf] if uf else list(candidatos)


def ufs_citadas(texto: str) -> set[str]:
    """UFs citadas como 'Estado do Rio de Janeiro' ou 'Macaé/RJ'."""
    ufs = {UFS[m.group(1)] for m in _ESTADO_POR_EXTENSO.finditer(normalizar(texto))}
    ufs.update(m.group(1) for m in _UF_APOS_BARRA.finditer(texto) if m.group(1) in SIGLAS_UF)
    return ufs


class ResolvedorLocal:
    def __init__(self, municipios: IndiceMunicipios) -> None:
        self._municipios = municipios

    def resolver(self, orgao: OrgaoInferido | None, unificado: bool = False, contexto: str = "") -> Local:
        """`contexto`: texto extra para achar a UF (descrição da página, começo do edital)."""
        if unificado:
            return Local("NACIONAL")
        if orgao is None:
            return Local(None, aviso="órgão não identificado: local do concurso desconhecido")
        if orgao.esfera == "MUNICIPAL":
            return self._municipal(orgao, contexto)
        if orgao.esfera == "FEDERAL":
            uf = orgao.uf or self._uf_do_tribunal_regional(orgao.nome)
            return Local("ESTADUAL", uf) if uf else Local("NACIONAL")
        uf = orgao.uf or _unica(ufs_citadas(f"{orgao.nome} {contexto}"))
        if uf:
            return Local("ESTADUAL", uf)
        return Local(None, aviso=f"UF do órgão '{orgao.nome}' não identificada")

    def _municipal(self, orgao: OrgaoInferido, contexto: str) -> Local:
        nome_municipio, candidatos = self._achar_municipio(orgao)
        if nome_municipio is None:
            return Local(None, orgao.uf, aviso=f"município do órgão '{orgao.nome}' não identificado")
        if len(candidatos) > 1:
            citadas = ufs_citadas(contexto)
            candidatos = [m for m in candidatos if m.uf in citadas] or candidatos
        aviso = None
        if len(candidatos) > 1:
            capitais = [m for m in candidatos if m.codigo_ibge in CAPITAIS]
            if len(capitais) != 1:
                ufs = ", ".join(sorted(m.uf for m in candidatos))
                return Local(None, aviso=f"município '{nome_municipio}' existe em mais de um estado ({ufs})")
            candidatos = capitais
            aviso = f"município '{nome_municipio}' tem homônimos: considerada a capital ({capitais[0].uf})"
        if not candidatos:
            return Local(None, orgao.uf, aviso=f"município '{nome_municipio}' não encontrado na lista do IBGE")
        municipio = candidatos[0]
        return Local("MUNICIPAL", municipio.uf, municipio.codigo_ibge, aviso)

    def _achar_municipio(self, orgao: OrgaoInferido) -> tuple[str | None, list[Municipio]]:
        """(nome usado, candidatos do IBGE). O nome inferido do órgão vem primeiro; sem ele (ou sem achar), tenta o
        trecho antes de "/UF" e os finais do nome depois de "de/da/do", do mais longo para o mais curto."""
        tentativas = [orgao.municipio] if orgao.municipio else []
        tentativas += [m.group(1).strip() for m in _ANTES_DA_BARRA.finditer(orgao.nome)]
        tentativas += re.split(r"\s+[-–]\s+", orgao.nome)[1:]  # "IPC - Arraial do Cabo"
        tentativas += [
            final
            for m in _PREPOSICAO.finditer(orgao.nome)
            if normalizar(final := orgao.nome[m.end() :]) not in _ASSUNTOS
        ]
        for nome in tentativas:
            candidatos = self._municipios.buscar(nome, orgao.uf)
            if candidatos:
                return nome, candidatos
        return (orgao.municipio, []) if orgao.municipio else (None, [])

    @staticmethod
    def _uf_do_tribunal_regional(nome_orgao: str) -> str | None:
        normal = normalizar(nome_orgao)
        if trt := _TRT_REGIAO.search(normal):
            return _TRT_UF.get(int(trt.group(1)))
        if trf := _TRF_REGIAO.search(normal):
            return _TRF_UF.get(int(trf.group(1)))
        return None


def _unica(ufs: set[str]) -> str | None:
    return next(iter(ufs)) if len(ufs) == 1 else None
