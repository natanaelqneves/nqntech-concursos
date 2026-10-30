from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")

# Escopo do site (seção 1 do contexto): só oportunidades — inscrições abertas ou ainda por abrir, previstos e
# prazo de isenção em curso. Concurso fora disso não tem a página relida nem PDFs baixados, com duas folgas:
# - inscrição encerrada há até DIAS_FOLGA_INSCRICAO dias continua acompanhada (prorrogações e reaberturas
#   costumam sair em cima do prazo);
# - a página é relida a cada DIAS_RELEITURA dias mesmo assim (reabertura tardia). Precisa ser menor que
#   DIAS_FORA_DA_LISTA_PARA_ENCERRAR (estruturacao.py): a releitura é o que marca o sinal como visto na fonte.
DIAS_FOLGA_INSCRICAO = 15
DIAS_RELEITURA = 7


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
