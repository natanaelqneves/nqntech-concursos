"""Segunda leitura, dirigida: completa os dados mínimos do site que a primeira leitura não trouxe.

Mínimos (o que a pessoa precisa para decidir): fim das inscrições, data da prova, salário de até e, se o edital
prevê isenção, o prazo para pedir. A primeira leitura (regras ou IA) usa um recorte por seções; em editais longos
o cronograma ou o quadro de remuneração ficam de fora. Aqui o edital inteiro (sem o conteúdo programático) é
varrido atrás de trechos com essas palavras e só esses trechos vão à IA, pedindo só os campos que faltam.
Mesma política da primeira leitura: uma chamada por edital (cache próprio), validação desconfiada, nada estimado.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from coletor.extratores.base import EditalExtraido
from coletor.ia.provedores import FalhaIA, Rodizio
from coletor.ia.recorte import _sem_conteudo_programatico
from coletor.texto import normalizar

log = logging.getLogger(__name__)

VERSAO = "lacunas-1"
MAX_CARACTERES = 14_000
JANELA = 700
MAX_POR_CAMPO = 5

# Palavras procuradas no texto sem acento e em minúsculas (mesmo comprimento do original, ver _sem_acento).
_PADROES: Mapping[str, re.Pattern[str]] = {
    "inscricao": re.compile(r"periodo de inscric|inscricoes (?:serao|estarao|poderao|ficam)|cronograma|"
                            r"inscric(?:ao|oes)[^.\n]{0,60}\d{1,2}[/.]\d{1,2}"),
    "prova": re.compile(r"prova objetiva|provas objetivas|aplicacao das provas|data da prova|data provavel|"
                        r"cronograma|serao realizadas? (?:em|no dia|na data)"),
    "salario": re.compile(r"remuneracao|vencimento|salario|subsidio|r\$ ?\d"),
    "isencao": re.compile(r"isencao"),
}  # fmt: skip

ESQUEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["inscricao_inicio", "inscricao_fim", "data_prova", "salarios", "isencao_inicio", "isencao_fim"],
    "properties": {
        "inscricao_inicio": {"type": ["string", "null"], "description": "início das inscrições (AAAA-MM-DD)"},
        "inscricao_fim": {"type": ["string", "null"], "description": "fim das inscrições (AAAA-MM-DD)"},
        "data_prova": {"type": ["string", "null"], "description": "data (prevista) da prova objetiva (AAAA-MM-DD)"},
        "salarios": {
            "type": "array",
            "description": "remuneração inicial de cada cargo citada nos trechos",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["cargo", "salario"],
                "properties": {"cargo": {"type": "string"}, "salario": {"type": ["number", "null"]}},
            },
        },
        "isencao_inicio": {"type": ["string", "null"], "description": "início do prazo para pedir isenção"},
        "isencao_fim": {"type": ["string", "null"], "description": "fim do prazo para pedir isenção (AAAA-MM-DD)"},
    },
}

INSTRUCOES = (
    "Você recebe trechos de um edital de concurso público brasileiro. Responda só com o JSON do esquema. "
    "Preencha apenas o que estiver escrito nos trechos; o que não aparecer fica null (nunca estime). Datas em "
    "AAAA-MM-DD; se o edital diz só 'data provável', use essa data. Salário = remuneração inicial do cargo em "
    "reais, como número (3200.50), um item por cargo. Prazo de isenção = período para pedir isenção da taxa."
)


def faltando(edital: EditalExtraido) -> list[str]:
    campos = []
    if edital.inscricao_fim is None:
        campos.append("inscricao")
    if edital.data_prova is None:
        campos.append("prova")
    if edital.cargos and all(c.salario is None for c in edital.cargos):
        campos.append("salario")
    if edital.isencoes and edital.isencao_fim is None:
        campos.append("isencao")
    return campos


def _sem_acento(texto: str) -> str:
    """Minúsculas sem acento com o MESMO comprimento do original (as posições servem para recortar o original)."""
    return "".join(unicodedata.normalize("NFKD", c)[0] if c.strip() else c for c in texto.lower())


def trechos_dirigidos(texto: str, campos: list[str], maximo: int = MAX_CARACTERES) -> str:
    util = _sem_conteudo_programatico(texto)
    busca = _sem_acento(util)
    janelas: list[tuple[int, int]] = []
    for campo in campos:
        for numero, achado in enumerate(_PADROES[campo].finditer(busca)):
            if numero >= MAX_POR_CAMPO:
                break
            janelas.append((max(0, achado.start() - JANELA // 3), min(len(util), achado.start() + JANELA)))
    juntas: list[list[int]] = []
    for inicio, fim in sorted(janelas):
        if juntas and inicio <= juntas[-1][1]:
            juntas[-1][1] = max(juntas[-1][1], fim)
        else:
            juntas.append([inicio, fim])
    partes, usado = [], 0
    for inicio, fim in juntas:
        if usado >= maximo:
            break
        trecho = util[inicio:fim][: maximo - usado]
        partes.append(trecho)
        usado += len(trecho)
    return "\n[...]\n".join(partes)


def _data(valor: Any, hoje: date) -> date | None:
    try:
        dia = date.fromisoformat(str(valor or "")[:10])
    except ValueError:
        return None
    return dia if hoje.year - 2 <= dia.year <= hoje.year + 3 else None


def _salario(valor: Any) -> Decimal | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = Decimal(str(valor)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    return numero if Decimal(300) < numero < Decimal(150_000) else None


def aplicar(edital: EditalExtraido, dados: Mapping[str, Any], hoje: date) -> EditalExtraido:
    """Preenche só os campos ainda vazios; nunca troca o que a primeira leitura achou."""
    inicio, fim = _data(dados.get("inscricao_inicio"), hoje), _data(dados.get("inscricao_fim"), hoje)
    if inicio and fim and fim < inicio:
        inicio = fim = None
    prova = _data(dados.get("data_prova"), hoje)
    novo_fim = edital.inscricao_fim or fim
    if prova and novo_fim and prova < novo_fim:
        prova = None  # prova antes do fim das inscrições: leitura errada
    isencao_inicio, isencao_fim = _data(dados.get("isencao_inicio"), hoje), _data(dados.get("isencao_fim"), hoje)
    if isencao_inicio and isencao_fim and isencao_fim < isencao_inicio:
        isencao_inicio = isencao_fim = None

    salarios = [(normalizar(str(s.get("cargo") or "")), _salario(s.get("salario")))
                for s in dados.get("salarios") or [] if isinstance(s, Mapping)]  # fmt: skip
    salarios = [(nome, valor) for nome, valor in salarios if valor is not None]
    cargos = list(edital.cargos)
    if salarios and all(c.salario is None for c in cargos):
        unico = {v for _, v in salarios}
        for i, cargo in enumerate(cargos):
            nome = normalizar(f"{cargo.nome} {cargo.especialidade or ''}")
            casado = next((v for n, v in salarios if n and (n in nome or normalizar(cargo.nome) in n)), None)
            if casado is None and len(unico) == 1:
                casado = next(iter(unico))  # um só valor no edital: vale para todos os cargos
            if casado is not None:
                cargos[i] = replace(cargo, salario=casado)

    preenchido = replace(
        edital,
        inscricao_inicio=edital.inscricao_inicio or (inicio if not edital.inscricao_fim else None),
        inscricao_fim=novo_fim,
        data_prova=edital.data_prova or prova,
        cargos=tuple(cargos),
        isencao_inicio=edital.isencao_inicio or (isencao_inicio if edital.isencoes else None),
        isencao_fim=edital.isencao_fim or (isencao_fim if edital.isencoes else None),
    )
    resolvidos = {
        "período de inscrição": preenchido.inscricao_fim is not None,
        "data da prova": preenchido.data_prova is not None,
        "salár": any(c.salario for c in preenchido.cargos),
        "período para pedir isenção": preenchido.isencao_fim is not None,
    }
    avisos = tuple(a for a in preenchido.avisos if not any(chave in a and ok for chave, ok in resolvidos.items()))
    return replace(preenchido, avisos=avisos)


class CompletadorIA:
    """Uma chamada por edital com lacuna; usa o mesmo rodízio (e o mesmo teto) da primeira leitura."""

    def __init__(
        self,
        rodizio: Rodizio,
        ler_cache: Callable[[str, str], dict[str, Any] | None],
        gravar_cache: Callable[[str, str, str, dict[str, Any] | None, str], None],
    ) -> None:
        self._rodizio, self._ler_cache, self._gravar_cache = rodizio, ler_cache, gravar_cache

    def completar(self, edital: EditalExtraido, texto: str, sha256: str | None, hoje: date) -> EditalExtraido:
        campos = faltando(edital)
        if not campos:
            return edital
        guardado = self._ler_cache(sha256, VERSAO) if sha256 else None
        if guardado is not None:
            return aplicar(edital, guardado["resposta"], hoje) if guardado.get("resposta") else edital
        trechos = trechos_dirigidos(texto, campos)
        if not trechos or not self._rodizio.disponivel:
            return edital
        try:
            resposta, provedor = self._rodizio.gerar(INSTRUCOES, trechos, ESQUEMA)
        except FalhaIA as erro:  # não vai ao cache: na próxima execução tenta de novo
            log.info("lacunas: IA indisponível (%s)", erro)
            return edital
        if sha256:
            self._gravar_cache(sha256, VERSAO, f"{provedor.nome}/{provedor.modelo}", resposta, ",".join(campos))
        completo = aplicar(edital, resposta, hoje)
        log.info("lacunas %s: %d caracteres; faltava %s, agora faltam %s", provedor.nome, len(trechos), campos,
                 faltando(completo) or "nada")  # fmt: skip
        return completo
