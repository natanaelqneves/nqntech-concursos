from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")


@dataclass(frozen=True)
class ResumoEtapa:
    etapa: str
    status: str  # SUCESSO | PARCIAL | FALHA (mesmos valores de execucao_coleta.status)
    itens_novos: int = 0
    mensagem: str | None = None
    fonte: str | None = None


def agora() -> datetime:
    return datetime.now(FUSO)


def hoje() -> date:
    return agora().date()


def status_por_falhas(falhas: list[str] | tuple[str, ...], total: int) -> str:
    if not falhas:
        return "SUCESSO"
    return "FALHA" if total == 0 else "PARCIAL"
