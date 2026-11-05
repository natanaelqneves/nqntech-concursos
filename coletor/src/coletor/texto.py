"""Utilitários de texto em português usados na classificação e na extração."""

from __future__ import annotations

import re
import unicodedata
from contextlib import suppress
from datetime import date
from decimal import Decimal, InvalidOperation

MESES = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

UFS = {
    "acre": "AC",
    "alagoas": "AL",
    "amapa": "AP",
    "amazonas": "AM",
    "bahia": "BA",
    "ceara": "CE",
    "distrito federal": "DF",
    "espirito santo": "ES",
    "goias": "GO",
    "maranhao": "MA",
    "mato grosso do sul": "MS",
    "mato grosso": "MT",
    "minas gerais": "MG",
    "para": "PA",
    "paraiba": "PB",
    "parana": "PR",
    "pernambuco": "PE",
    "piaui": "PI",
    "rio de janeiro": "RJ",
    "rio grande do norte": "RN",
    "rio grande do sul": "RS",
    "rondonia": "RO",
    "roraima": "RR",
    "santa catarina": "SC",
    "sao paulo": "SP",
    "sergipe": "SE",
    "tocantins": "TO",
}

_ESPACOS = re.compile(r"\s+")
_DATA_EXTENSO = re.compile(r"(\d{1,2})(?:º|o)?\s+de\s+([a-z]+)\s+de\s+(\d{4})")  # "1º" vira "1o" ao normalizar
_DATA_NUMERICA = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_VALOR = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})", re.IGNORECASE)


def sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento, travessões viram hífen e espaços colapsados — base de toda comparação."""
    texto = sem_acento(texto).lower().replace("–", "-").replace("—", "-")
    return _ESPACOS.sub(" ", texto).strip()


def colapsar_espacos(texto: str) -> str:
    return _ESPACOS.sub(" ", texto).strip()


def contem_termo(texto_normalizado: str, termo: str) -> bool:
    # Palavra inteira: "ti" casa com "área de ti", mas não com "ativo" nem "partidária".
    return re.search(rf"(?<![a-z0-9]){re.escape(normalizar(termo))}(?![a-z0-9])", texto_normalizado) is not None


def todas_as_datas(trecho: str) -> list[date]:
    """Datas do trecho na ordem em que aparecem, em '20 de outubro de 2026' ou '20/10/2026'.
    Datas impossíveis (31 de fevereiro) são ignoradas."""
    normal = normalizar(trecho)
    achadas: list[tuple[int, date]] = []
    for m in _DATA_EXTENSO.finditer(normal):
        if mes := MESES.get(m.group(2)):
            with suppress(ValueError):
                achadas.append((m.start(), date(int(m.group(3)), mes, int(m.group(1)))))
    for m in _DATA_NUMERICA.finditer(normal):
        with suppress(ValueError):
            achadas.append((m.start(), date(int(m.group(3)), int(m.group(2)), int(m.group(1)))))
    return [d for _, d in sorted(achadas)]


def data_por_extenso(trecho: str) -> date | None:
    datas = todas_as_datas(trecho)
    return datas[0] if datas else None


def valor_monetario(texto: str) -> Decimal | None:
    m = _VALOR.search(texto)
    return converter_valor(m.group(1)) if m else None


def valores_monetarios(texto: str) -> list[Decimal]:
    return [v for v in (converter_valor(m.group(1)) for m in _VALOR.finditer(texto)) if v is not None]


def converter_valor(numero_br: str) -> Decimal | None:
    try:
        return Decimal(numero_br.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def uf_por_nome(texto: str) -> str | None:
    """UF citada como 'Estado da Paraíba', 'do Paraná' etc. Nomes mais longos primeiro (Mato Grosso do Sul)."""
    normal = normalizar(texto)
    for nome in sorted(UFS, key=len, reverse=True):
        if re.search(rf"\b(?:estado d[eoa]s?|d[eoa]) {re.escape(nome)}\b", normal):
            return UFS[nome]
    return None


def slugificar(texto: str) -> str:
    """Mesma regra da migration de municípios (scripts/captura/gerar_municipios_ibge.py): 'Macaé' → 'macae'."""
    return re.sub(r"[^a-z0-9]+", "-", sem_acento(texto).lower()).strip("-")


def limitar(texto: str | None, maximo: int) -> str | None:
    if texto is None:
        return None
    # \x00 é recusado pelo PostgreSQL em colunas text; aparece em PDFs mal formados.
    texto = texto.replace("\x00", "")
    return texto if len(texto) <= maximo else texto[:maximo]


_PREPOSICOES = frozenset(
    {
        "de",
        "da",
        "do",
        "das",
        "dos",
        "e",
        "em",
        "para",
        "a",
        "o",
        "as",
        "os",
        "à",
        "às",
        "ao",
        "aos",
        "com",
        "na",
        "no",
        "nas",
        "nos",
        "por",
        "pela",
        "pelo",
        "ou",
    }
)
_SIGLAS_MINUSCULAS = frozenset({"ti", "tic"})
# Siglas com vogal que a regra "sem vogal = sigla" não pega. Nomes que viraram palavra (Petrobras, Embrapa, Detran
# em textos corridos) ficam de fora de propósito: a forma usual deles é só a inicial maiúscula.
_SIGLAS_COM_VOGAL = frozenset(
    [
        "ABIN",
        "AGE",
        "AGU",
        "ALEAM",
        "ALEAP",
        "ALEMG",
        "ALEPA",
        "ALEPB",
        "ALEPE",
        "ALERJ",
        "ALESP",
        "ALECE",
        "ALEGO",
        "ALEMS",
        "ALES",
        "ALESC",
        "ALETO",
        "ANA",
        "ANAC",
        "ANATEL",
        "ANEEL",
        "ANM",
        "ANP",
        "ANS",
        "ANTAQ",
        "ANVISA",
        "AOCP",
        "BACEN",
        "CAPES",
        "CAPS",
        "CEBRASPE",
        "CESGRANRIO",
        "CNU",
        "COMPERVE",
        "CONSULPLAN",
        "CRAS",
        "CREAS",
        "DEPEN",
        "DETRAN",
        "DNIT",
        "DPE",
        "DPU",
        "EBSERH",
        "FEPESE",
        "FUNAI",
        "FUNDATEC",
        "FUNRIO",
        "IADES",
        "IBADE",
        "IBAM",
        "IBAMA",
        "IBFC",
        "IBGE",
        "ICMBIO",
        "IDECAN",
        "INCRA",
        "INEP",
        "INPI",
        "INSS",
        "IPEA",
        "IPHAN",
        "MPE",
        "MPU",
        "OAB",
        "PGE",
        "PGM",
        "PRODAM",
        "SAEB",
        "SAMU",
        "SEAD",
        "SEAP",
        "SEDUC",
        "SEFAZ",
        "SEJUS",
        "SEJUSP",
        "SELECON",
        "SEMOB",
        "SEPLAG",
        "SESA",
        "SESAU",
        "SESP",
        "SUS",
        "TCE",
        "TCM",
        "TCU",
        "UEPB",
        "UERJ",
        "UESPI",
        "UNEB",
        "UNEMAT",
        "UPA",
        "VUNESP",
    ]
)
# "XXXIX Concurso", "II Processo Seletivo"; a forma válida evita confundir com palavras como "CIVIL".
_ROMANO = re.compile(r"^M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$")
# Instituto/universidade federal: IFPB, IFRN, UFPB, UFCG, UFRGS.
_SIGLA_FEDERAL = re.compile(r"^(?:IF|UF)[A-Z]{2,4}$")
_ABREVIACAO = re.compile(r"^(?:[A-Z]\.)+[A-Z]\.?$")  # "S.A.", "E.E."


def titulo_portugues(texto: str) -> str:
    """'TRIBUNAL DE JUSTIÇA DA PARAÍBA' → 'Tribunal de Justiça da Paraíba': inicial maiúscula, preposições em
    minúsculas e siglas em caixa alta. Em texto todo maiúsculo trata todas as palavras; em texto misto, só os
    trechos com duas ou mais palavras seguidas em caixa alta ("Concurso PREFEITURA DE SAPÉ"), porque uma palavra
    maiúscula isolada no meio de texto normal costuma ser sigla de propósito. Idempotente."""
    texto = colapsar_espacos(texto)
    palavras = texto.split()
    if not palavras:
        return texto
    maiusculas = [_em_caixa_alta(p) for p in palavras]
    if all(maiusculas):
        return " ".join(_palavra_titulo(p, i) for i, p in enumerate(palavras))
    resultado = list(palavras)
    i = 0
    while i < len(palavras):
        if not maiusculas[i]:
            i += 1
            continue
        fim = i
        while fim < len(palavras) and maiusculas[fim]:
            fim += 1
        trecho = range(i, fim)
        if sum(1 for j in trecho if _tem_letras(palavras[j])) >= 2:
            for j in trecho:
                resultado[j] = _palavra_titulo(palavras[j], j)
        i = fim
    return " ".join(resultado)


def _tem_letras(palavra: str) -> bool:
    return any(c.isalpha() for c in palavra)


def _em_caixa_alta(palavra: str) -> bool:
    # Sem letras ("2026", "–") não quebra o trecho: "PREFEITURA – SAPÉ" é um trecho só.
    return palavra == palavra.upper()


def _eh_sigla(palavra: str) -> bool:
    if _ABREVIACAO.match(palavra.strip(",;:()")):
        return True
    base = palavra.strip(".,;:()")
    if not base or not base.isalpha() or base != base.upper():
        return False
    return (
        not set(normalizar(base)) & set("aeiou")
        or base in _SIGLAS_COM_VOGAL
        or base in _SIGLAS_UF
        or _SIGLA_FEDERAL.match(base) is not None
        or _ROMANO.match(base) is not None
    )


def _palavra_titulo(palavra: str, posicao: int) -> str:
    if "/" in palavra or "-" in palavra.strip("-"):
        # "Lages/SC", "SEAD-AP", "Mun.-TI": cada parte é tratada sozinha; UF depois de barra ou hífen fica maiúscula.
        partes = re.split(r"([/-])", palavra)
        return "".join(
            p if p in "/-" or (i > 1 and partes[i - 1] in "/-" and p in _SIGLAS_UF) else _palavra_titulo(p, posicao + i)
            for i, p in enumerate(partes)
        )
    minuscula = palavra.lower()
    if any(c.isdigit() for c in palavra) or minuscula.strip(".") in _SIGLAS_MINUSCULAS:
        return palavra.upper() if minuscula.strip(".") in _SIGLAS_MINUSCULAS else palavra
    if _eh_sigla(palavra):
        return palavra
    if posicao > 0 and minuscula in _PREPOSICOES:
        return minuscula
    return minuscula[:1].upper() + minuscula[1:]


_SIGLAS_UF = frozenset(UFS.values())


def escolaridade_por_texto(texto: str | None) -> str | None:
    """'MÉDIO na modalidade MAGISTÉRIO', 'NIVEL FUNDAMENTAL', 'Superior completo', 'MÉDIO/TECNICO'..."""
    normal = normalizar(texto or "")
    for termo, codigo in (
        ("superior", "SUPERIOR"),
        ("tecnic", "TECNICO"),
        ("medio", "MEDIO"),
        ("fundamental", "FUNDAMENTAL"),
        ("alfabetizado", "FUNDAMENTAL"),
    ):
        if termo in normal:
            return codigo
    return None
