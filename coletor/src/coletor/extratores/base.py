"""Contrato dos extratores de edital: texto do edital → dados estruturados + avisos.

Implementações são puras (sem rede nem banco) para serem trocáveis — por regras hoje, por LLM na fase 10.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class CargoExtraido:
    nome: str
    especialidade: str | None = None
    escolaridade: str | None = None
    vagas: int | None = None
    cadastro_reserva: bool = False
    salario: Decimal | None = None
    uf_lotacao: str | None = None
    disciplinas: tuple[str, ...] = ()  # só os nomes, nunca o conteúdo programático
    tem_redacao: bool | None = None  # prova discursiva/redação; None = não identificado ("confira o edital")


@dataclass(frozen=True)
class IsencaoPrevista:
    codigo: str  # concursos.isencao_tipo.codigo
    observacao: str | None = None


@dataclass(frozen=True)
class EventoCalendario:
    evento: str
    inicio: date | None = None  # None = "a definir"
    fim: date | None = None


@dataclass(frozen=True)
class EditalExtraido:
    orgao: str | None = None
    numero_edital: str | None = None
    ano: int | None = None
    cargos: tuple[CargoExtraido, ...] = ()
    inscricao_inicio: date | None = None
    inscricao_fim: date | None = None
    data_prova: date | None = None
    taxa_min: Decimal | None = None
    taxa_max: Decimal | None = None
    isencoes: tuple[IsencaoPrevista, ...] = ()
    isencao_inicio: date | None = None
    isencao_fim: date | None = None
    eventos: tuple[EventoCalendario, ...] = ()
    avisos: tuple[str, ...] = field(default=())


class Extrator(Protocol):
    def extrair(self, texto: str) -> EditalExtraido:
        """Extrai o que conseguir do texto do edital. Nunca levanta exceção por dado ausente:
        o que não foi encontrado vira um aviso legível em `avisos`."""
        ...
