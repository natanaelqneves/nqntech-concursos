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


def limitar(texto: str | None, maximo: int) -> str | None:
    if texto is None:
        return None
    # \x00 é recusado pelo PostgreSQL em colunas text; aparece em PDFs mal formados.
    texto = texto.replace("\x00", "")
    return texto if len(texto) <= maximo else texto[:maximo]


_PREPOSICOES = frozenset({"de", "da", "do", "das", "dos", "e", "em", "para", "a", "o", "com", "na", "no"})
_SIGLAS_MINUSCULAS = frozenset({"ti", "tic"})


def titulo_portugues(texto: str) -> str:
    """'TRIBUNAL DE JUSTIÇA DA PARAÍBA' → 'Tribunal de Justiça da Paraíba'. Só mexe em texto todo maiúsculo.
    Preserva siglas sem vogal ("PMSP"), UFs após barra ("Lages/SC"), códigos com dígitos ("CREF22") e TI/TIC."""
    texto = colapsar_espacos(texto)
    if texto != texto.upper() or not any(c.isalpha() for c in texto):
        return texto
    return " ".join(_palavra_titulo(p, i) for i, p in enumerate(texto.split()))


def _palavra_titulo(palavra: str, posicao: int) -> str:
    if "/" in palavra or "-" in palavra.strip("-"):
        # "Lages/SC", "Mun.-TI": cada parte é tratada sozinha; UF só é reconhecida depois da barra.
        partes = re.split(r"([/-])", palavra)
        return "".join(
            p if p in "/-" or (i > 1 and partes[i - 1] == "/" and p in _SIGLAS_UF) else _palavra_titulo(p, posicao + i)
            for i, p in enumerate(partes)
        )
    minuscula = palavra.lower()
    if (
        any(c.isdigit() for c in palavra)
        or minuscula.strip(".") in _SIGLAS_MINUSCULAS
        or (palavra.isalpha() and not set(normalizar(palavra)) & set("aeiou"))
    ):
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
