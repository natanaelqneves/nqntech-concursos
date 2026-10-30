"""Órgão, esfera, UF e município a partir do título do concurso (ou do nome do órgão informado pela banca)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from coletor.texto import UFS, colapsar_espacos, normalizar, uf_por_nome

SIGLAS_UF = frozenset(UFS.values())


@dataclass(frozen=True)
class OrgaoInferido:
    nome: str
    esfera: str | None
    uf: str | None
    municipio: str | None


_PREFIXO_TITULO = re.compile(
    r"^(?:[ivxlc]+\s+)?(?:concurso p[uú]blico|processo seletivo(?: p[uú]blico| simplificado)?|sele[cç][aã]o p[uú]blica)"
    r"(?:\s+nacional\s+unificado)?(?:\s+para\s+(?:provimento\s+de\s+cargos?\s+de\s+.+?\s+(?:d[oa]s?|n[oa]s?)\s+)?)?"
    r"(?:\s*(?:para|d[oa]s?|n[oa]s?|a|o)\s+)*",
    re.IGNORECASE,
)
# Sufixo descartável: " - Juiz Substituto", " (2026)", " 2026 - Guarda". Só traço com espaço em volta conta:
# "Procuradoria-Geral" e "Controladoria-Geral" são parte do nome.
_SUFIXO_TITULO = re.compile(r"\s+(?:[-–]\s.*|\(.*|\d{4}\b.*)$")
_REGIAO = re.compile(r"\s+[-–]\s+(\d{1,2})\s*[ªa]\s+regi[aã]o\b", re.IGNORECASE)
_JUIZ_FEDERAL_REGIAO = re.compile(r"juiz(?:a)? federal\b.*?\b(\d{1,2})\s*[ªa]\s+regi[aã]o", re.IGNORECASE)
# UF colada no nome: sigla ("SEAD-AP", "SEPLAG/RJ", "AGE-MG") ou município com barra ("Fraiburgo/SC").
_SIGLA_COM_UF = re.compile(r"(?:\b[A-Z]{2,}-|/\s?)([A-Z]{2})\b")
# Início do nome do órgão quando o título traz texto antes dele ("XXXIX Concurso para Ingresso na Carreira do
# Ministério Público...", "Juiz Leigo do Tribunal de Justiça...").
_NUCLEO_ORGAO = re.compile(
    r"\b(prefeitura|c[aâ]mara|tribunal|minist[eé]rio|secretaria|pol[ií]cia|assembleia|defensoria|procuradoria|"
    r"controladoria|advocacia|ag[eê]ncia|banco|universidade|instituto|conselho|empresa|companhia|funda[cç][aã]o|"
    r"receita|guarda|corpo de bombeiros|departamento|superintend[eê]ncia|autarquia|hospital|servi[cç]o|caixa|"
    r"ind[uú]strias|senado|comiss[aã]o|autoridade)\b",
    re.IGNORECASE,
)

_MUNICIPAL = re.compile(
    r"\b(prefeitura|camara municipal|camara d[eoa]|municipio|guarda (civil )?municipal|secretaria municipal|"
    r"camara de vereadores)\b"
)
_FEDERAL = re.compile(
    r"\b((?<!distrito )federal|nacional|da uniao|camara dos deputados|do brasil|brasileir[ao]|tribunal regional|"
    r"tribunal superior|justica do trabalho|"
    r"justica eleitoral|justica militar|conselho superior|conselho nacional|trf|trt|tre|tst|stj|stf|tse|cnj|csjt|"
    r"inss|ibge|dataprev|serpro|caixa economica|petrobras|correios|nav brasil|abdi|ebserh|embrapa|abin|"
    r"ministerio(?! publico d[eo] estado)(?! publico estadual))\b"
)
_ESTADUAL = re.compile(
    r"\b(do estado|estadual|governo d[oe]|assembleia legislativa|tribunal de justica|tribunal de contas do estado|"
    r"ministerio publico|defensoria publica|procuradoria-geral do estado|procuradoria geral do estado|"
    r"policia (militar|civil|penal)|corpo de bombeiros militar|secretaria (de estado|da fazenda|estadual)|"
    r"controladoria-geral do estado|controladoria geral do estado)\b"
)
_MUNICIPIO_NOME = re.compile(
    r"(?:prefeitura|c[aâ]mara|munic[ií]pio)\s+(?:municipal\s+)?d[eoa]s?\s+(.+?)(?:\s*/\s*([A-Z]{2}))?$",
    re.IGNORECASE,
)


def inferir_orgao(titulo_concurso: str) -> OrgaoInferido | None:
    """'Concurso Público para o Tribunal de Justiça do Estado da Paraíba' → órgão, esfera e UF."""
    titulo = colapsar_espacos(titulo_concurso)
    if juiz_federal := _JUIZ_FEDERAL_REGIAO.search(titulo):
        regiao_federal = int(juiz_federal.group(1))
        return OrgaoInferido(f"Tribunal Regional Federal da {regiao_federal}ª Região", "FEDERAL", None, None)

    sigla = _SIGLA_COM_UF.search(titulo)
    uf_sigla = sigla.group(1) if sigla and sigla.group(1) in SIGLAS_UF else None
    regiao = _REGIAO.search(titulo)

    nome = colapsar_espacos(_PREFIXO_TITULO.sub("", titulo))
    nome = _SUFIXO_TITULO.sub("", nome).strip(" -–,.")
    if (nucleo := _NUCLEO_ORGAO.search(nome)) is not None and nucleo.start() > 0:
        nome = nome[nucleo.start() :]
    if regiao is not None and not re.search(r"\bregiao\b", normalizar(nome)):
        nome = f"{nome} da {int(regiao.group(1))}ª Região"
    if len(nome) < 4:
        return None
    nome = nome[0].upper() + nome[1:]

    normal = normalizar(f"{nome} {titulo}")  # o título inteiro ajuda: a sigla no fim ("- Dataprev") indica a esfera
    uf = uf_por_nome(nome) or uf_sigla
    if _MUNICIPAL.search(normalizar(nome)):
        municipio = _MUNICIPIO_NOME.search(nome)
        nome_municipio = municipio.group(1).strip(" -–,.") if municipio else None
        uf_barra = municipio.group(2) if municipio and municipio.group(2) in SIGLAS_UF else None
        return OrgaoInferido(nome, "MUNICIPAL", uf_barra or uf, nome_municipio)
    if _FEDERAL.search(normal):
        return OrgaoInferido(nome, "FEDERAL", uf, None)
    if _ESTADUAL.search(normal) or uf:
        return OrgaoInferido(nome, "ESTADUAL", uf, None)
    return OrgaoInferido(nome, None, None, None)
