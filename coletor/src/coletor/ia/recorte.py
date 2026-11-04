"""Recorta do edital só o que a IA precisa, para gastar poucos tokens.

Editais têm de 20 a 200 páginas, quase tudo conteúdo programático e regras de prova. Os dados do site estão na
abertura, no quadro de cargos/vagas, nas inscrições/taxa, na isenção e no cronograma.
"""

from __future__ import annotations

import re

from coletor.texto import normalizar

MAX_CARACTERES = 24_000  # ~6 mil tokens de entrada
_ABERTURA = 3_500
_POR_SECAO = 3_000

# Título de seção: numerado ("5. DA ISENÇÃO", "3.1 Dos cargos") ou todo em maiúsculas ("CRONOGRAMA PREVISTO").
_NUMERADO = re.compile(r"^\s*\d{1,2}(?:\.\d{1,2})?\s*[.)-]?\s+(?:d[oa]s?\s+)?(?P<chave>[a-z ]+)")
_CHAVES = (
    ("cargos", re.compile(r"^(?:cargos?|quadro de vagas|vagas)\b")),
    ("remuneracao", re.compile(r"^(?:remuneracao|vencimentos?)\b")),
    ("inscricoes", re.compile(r"^inscric(?:ao|oes)\b")),
    ("taxa", re.compile(r"^taxa de inscricao\b")),
    ("isencao", re.compile(r"^isencao\b")),
    ("cronograma", re.compile(r"^(?:cronograma|datas)\b")),
    ("provas", re.compile(r"^(?:provas?|prova objetiva|etapas)\b")),
)
# Daqui em diante só há conteúdo programático: nunca vai para a IA.
_CONTEUDO_PROGRAMATICO = re.compile(r"^\s*anexo\b.{0,40}conteudos? programatico", re.MULTILINE)


def recortar(texto: str, maximo: int = MAX_CARACTERES) -> str:
    util = _sem_conteudo_programatico(texto)
    trechos: list[tuple[int, str]] = []
    vistos: set[str] = set()
    posicao = 0
    for linha in util.split("\n"):
        inicio = posicao
        posicao += len(linha) + 1
        if inicio < _ABERTURA or len(linha.strip()) > 90:
            continue
        chave = _chave_de_titulo(linha)
        if chave is None or chave in vistos:
            continue
        vistos.add(chave)
        trechos.append((inicio, util[inicio : inicio + _POR_SECAO]))

    partes = [util[:_ABERTURA]]
    usado = len(partes[0])
    for _, trecho in sorted(trechos):
        if usado >= maximo:
            break
        trecho = trecho[: maximo - usado]
        partes.append(f"\n[...]\n{trecho}")
        usado += len(trecho)
    return "".join(partes)[:maximo]


def _chave_de_titulo(linha: str) -> str | None:
    normal = normalizar(linha)
    m = _NUMERADO.match(normal)
    if m is not None:
        resto = m.group("chave")
    elif sum(c.isupper() for c in linha) > 0.7 * max(1, sum(c.isalpha() for c in linha)):
        resto = re.sub(r"^(?:anexo [ivxl]+\s*-?\s*)?(?:d[oa]s?\s+)?", "", normal)
    else:
        return None
    return next((nome for nome, padrao in _CHAVES if padrao.match(resto)), None)


def normalizar_linhas(texto: str) -> str:
    # split("\n") e não splitlines(): este trata \f (quebra de página do PDF) como linha e desalinharia posições.
    return "\n".join(normalizar(linha) for linha in texto.split("\n"))


def _sem_conteudo_programatico(texto: str) -> str:
    """Corta no anexo de conteúdo programático. Usa a última menção (o sumário também cita o anexo, no começo) e
    preserva um cronograma que venha em anexo posterior."""
    ocorrencias = list(_CONTEUDO_PROGRAMATICO.finditer(normalizar_linhas(texto)))
    if not ocorrencias:
        return texto
    linha = normalizar_linhas(texto)[: ocorrencias[-1].start()].count("\n")
    corte = sum(len(trecho) + 1 for trecho in texto.split("\n")[:linha])
    if corte < len(texto) * 0.2:  # cedo demais: é o sumário, não o anexo
        return texto
    resto = texto[corte:]
    cronograma = re.search(r"^.*\bCRONOGRAMA\b.*$", resto, re.MULTILINE)
    return texto[:corte] + (
        "" if cronograma is None else "\n" + resto[cronograma.start() : cronograma.start() + _POR_SECAO]
    )
