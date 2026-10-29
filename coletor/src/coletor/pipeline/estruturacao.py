"""Etapa 4: texto do edital mais recente → campos do concurso, quadro de cargos e avisos de extração.

Roda sobre o texto já gravado (o PDF não existe mais), por isso pode ser repetida a qualquer momento:
um extrator melhorado reprocessa tudo zerando concurso.edital_documento_id.
"""

from __future__ import annotations

import logging
from datetime import date

from coletor.db import Repositorio
from coletor.extratores import extrator_para_banca
from coletor.extratores.base import EditalExtraido
from coletor.pipeline.comum import ResumoEtapa, agora, hoje

log = logging.getLogger(__name__)

DIAS_FORA_DA_LISTA_PARA_ENCERRAR = 10


def situacao_por_datas(edital: EditalExtraido, referencia: date) -> str:
    if edital.inscricao_fim is not None and referencia <= edital.inscricao_fim:
        return "INSCRICOES_ABERTAS"
    return "EM_ANDAMENTO"


def executar_estruturacao(repo: Repositorio) -> ResumoEtapa:
    inicio = agora()
    pendentes = repo.concursos_para_estruturar()
    repo.conn.commit()
    estruturados = 0
    falhas: list[str] = []
    for concurso in pendentes:
        extrator = extrator_para_banca(concurso["banca"])
        if extrator is None:
            continue
        try:
            edital = extrator.extrair(concurso["texto_extraido"] or "")
            repo.aplicar_edital(concurso["id"], concurso["documento_id"], edital, situacao_por_datas(edital, hoje()))
            estruturados += 1
            log.info(
                "concurso %d estruturado: %d cargos, avisos=%s",
                concurso["id"],
                len(edital.cargos),
                list(edital.avisos) or "-",
            )
        except Exception as erro:
            log.exception("falha ao estruturar o concurso %d", concurso["id"])
            falhas.append(f"concurso {concurso['id']}: {erro}")

    alterados = repo.atualizar_situacoes_por_data(hoje(), DIAS_FORA_DA_LISTA_PARA_ENCERRAR)
    if alterados:
        log.info("%d concursos mudaram de situação pela data/ausência na fonte", alterados)
    status = "SUCESSO" if not falhas else ("FALHA" if estruturados == 0 else "PARCIAL")
    mensagem = "; ".join(falhas[:10]) or None
    repo.registrar_execucao("ESTRUTURACAO", inicio, status, estruturados, mensagem)
    return ResumoEtapa("ESTRUTURACAO", status, estruturados, mensagem)
