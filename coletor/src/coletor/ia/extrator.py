"""Junta triagem, recorte, cache, provedores e validação, e combina o resultado com o extrator de regras."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from coletor.extratores.base import EditalExtraido
from coletor.extratores.secoes import (
    Isencoes,
    atribuir_disciplinas,
    calendario,
    quadros_de_disciplinas,
    redacao_por_cargo,
)
from coletor.extratores.secoes import extrair_isencoes as isencoes_por_regras
from coletor.ia.esquema import ESQUEMA, INSTRUCOES, VERSAO, para_edital
from coletor.ia.provedores import FalhaIA, Rodizio
from coletor.ia.recorte import recortar
from coletor.ia.triagem import triar

log = logging.getLogger(__name__)

# Avisos das regras que indicam lacuna nos dados principais: só então vale gastar uma chamada de IA.
_LACUNAS = (
    "quadro de cargos/vagas não encontrado",
    "vagas de cada cargo não identificadas",
    "vagas e salários de cada cargo não identificados",
    "período de inscrição não encontrado",
    "taxa de inscrição não encontrada",
    "período para pedir isenção não identificado",
    "isenção citada, mas a seção não foi identificada",
)


@dataclass(frozen=True)
class ResultadoIA:
    edital: EditalExtraido | None
    origem: str  # "cache", "<provedor>/<modelo>", "triagem" (não é edital), "falha"
    motivo: str = ""


def precisa_de_ia(regras: EditalExtraido | None) -> bool:
    if regras is None:
        return True
    if not regras.cargos or regras.inscricao_fim is None:
        return True
    return any(aviso.startswith(lacuna) for aviso in regras.avisos for lacuna in _LACUNAS)


class ExtratorIA:
    """Uma instância por execução (o rodízio guarda limites e o teto de chamadas)."""

    def __init__(
        self,
        rodizio: Rodizio,
        ler_cache: Callable[[str, str], dict[str, Any] | None],
        gravar_cache: Callable[[str, str, str, dict[str, Any] | None, str], None],
        max_caracteres: int,
    ) -> None:
        self._rodizio = rodizio
        self._ler_cache = ler_cache
        self._gravar_cache = gravar_cache
        self._max = max_caracteres

    def extrair(self, texto: str, sha256: str | None, hoje: date) -> ResultadoIA:
        if sha256:
            guardado = self._ler_cache(sha256, VERSAO)
            if guardado is not None:
                if guardado.get("resposta") is None:
                    return ResultadoIA(None, "cache", guardado.get("motivo") or "não é edital de abertura")
                return ResultadoIA(self._montar(guardado["resposta"], texto, hoje), "cache")

        triagem = triar(texto)
        if not triagem.valido:
            if sha256:  # descarte também é guardado: o mesmo PDF não passa pela triagem de novo
                self._gravar_cache(sha256, VERSAO, "triagem", None, triagem.motivo)
            return ResultadoIA(None, "triagem", triagem.motivo)
        if not self._rodizio.disponivel:
            return ResultadoIA(None, "falha", "sem provedor disponível nesta execução")

        trecho = recortar(texto, self._max)
        try:
            resposta, provedor = self._rodizio.gerar(INSTRUCOES, trecho, ESQUEMA)
        except FalhaIA as erro:  # não vai ao cache: amanhã tenta de novo
            return ResultadoIA(None, "falha", str(erro))
        origem = f"{provedor.nome}/{provedor.modelo}"
        if sha256:
            self._gravar_cache(sha256, VERSAO, origem, resposta, triagem.motivo)
        log.info("edital lido por IA (%s): %d caracteres enviados", origem, len(trecho))
        return ResultadoIA(self._montar(resposta, texto, hoje), origem)

    def completar(self, edital: EditalExtraido, texto: str, sha256: str | None, hoje: date) -> EditalExtraido:
        """Segunda leitura dirigida aos dados mínimos que faltaram (ver ia/lacunas.py)."""
        from coletor.ia.lacunas import CompletadorIA

        return CompletadorIA(self._rodizio, self._ler_cache, self._gravar_cache).completar(edital, texto, sha256, hoje)

    @staticmethod
    def _montar(resposta: dict[str, Any], texto: str, hoje: date) -> EditalExtraido:
        edital, _uf = para_edital(resposta, hoje)
        return completar_com_secoes(edital, texto)


def completar_com_secoes(edital: EditalExtraido, texto: str) -> EditalExtraido:
    """Calendário, disciplinas e discursiva vêm das regras comuns (não custam tokens)."""
    isencoes = isencoes_por_regras(texto)
    if not edital.isencoes and isencoes.tipos:
        edital = replace(edital, isencoes=isencoes.tipos, isencao_inicio=isencoes.inicio, isencao_fim=isencoes.fim)
    periodo = Isencoes(edital.isencoes, edital.isencao_inicio, edital.isencao_fim)
    eventos = calendario(texto, periodo, (edital.inscricao_inicio, edital.inscricao_fim), edital.data_prova)
    cargos, _ = atribuir_disciplinas(edital.cargos, quadros_de_disciplinas(texto))
    cargos, _ = redacao_por_cargo(texto, cargos)
    return replace(edital, cargos=tuple(cargos), eventos=eventos)


def combinar(regras: EditalExtraido | None, ia: EditalExtraido) -> EditalExtraido:
    """Regras primeiro (são testadas contra editais reais); a IA só preenche o que faltou."""
    if regras is None:
        return ia
    cargos_regras_sem_vagas = all(c.vagas is None for c in regras.cargos)
    ia_tem_vagas = any(c.vagas for c in ia.cargos)
    usar_cargos_ia = bool(ia.cargos) and (not regras.cargos or (cargos_regras_sem_vagas and ia_tem_vagas))
    combinado = replace(
        regras,
        orgao=regras.orgao or ia.orgao,
        numero_edital=regras.numero_edital or ia.numero_edital,
        ano=regras.ano or ia.ano,
        cargos=ia.cargos if usar_cargos_ia else regras.cargos,
        inscricao_inicio=regras.inscricao_inicio or ia.inscricao_inicio,
        inscricao_fim=regras.inscricao_fim or ia.inscricao_fim,
        data_prova=regras.data_prova or ia.data_prova,
        taxa_min=regras.taxa_min if regras.taxa_max else ia.taxa_min,
        taxa_max=regras.taxa_max or ia.taxa_max,
        isencoes=regras.isencoes or ia.isencoes,
        isencao_inicio=regras.isencao_inicio if regras.isencoes else ia.isencao_inicio,
        isencao_fim=regras.isencao_fim if regras.isencoes else ia.isencao_fim,
        eventos=regras.eventos or ia.eventos,
        esfera=regras.esfera or ia.esfera,
        uf=regras.uf or ia.uf,
        municipio=regras.municipio or ia.municipio,
    )
    # Mantém só os avisos de lacunas que continuam abertas, mais os da validação da IA.
    resolvidos = {
        "quadro de cargos/vagas não encontrado": bool(combinado.cargos),
        "vagas de cada cargo não identificadas": usar_cargos_ia,
        "vagas e salários de cada cargo não identificados": usar_cargos_ia,
        "período de inscrição não encontrado": combinado.inscricao_fim is not None,
        "taxa de inscrição não encontrada": combinado.taxa_max is not None,
        "data da prova não encontrada": combinado.data_prova is not None,
        "período para pedir isenção não identificado": combinado.isencao_fim is not None,
        "isenção citada, mas a seção não foi identificada": bool(combinado.isencoes),
    }
    avisos = [a for a in regras.avisos if not any(a.startswith(k) and v for k, v in resolvidos.items())]
    avisos += [a for a in ia.avisos if not any(a.startswith(k) and v for k, v in resolvidos.items())]
    return replace(combinado, avisos=tuple(dict.fromkeys(avisos)))
