"""Etapa 4: texto do edital mais recente → campos do concurso, quadro de cargos e avisos de extração.

Roda sobre o texto já gravado (o PDF não existe mais), por isso pode ser repetida a qualquer momento:
um extrator melhorado reprocessa tudo zerando concurso.edital_documento_id.
"""

from __future__ import annotations

import logging
from datetime import date

from coletor.classificacao.orgao import inferir_orgao
from coletor.db import Repositorio
from coletor.extratores import extrator_para_banca
from coletor.extratores.base import EditalExtraido
from coletor.ia.extrator import ExtratorIA, combinar, precisa_de_ia
from coletor.pipeline.comum import ResumoEtapa, agora, hoje

log = logging.getLogger(__name__)

DIAS_FORA_DA_LISTA_PARA_ENCERRAR = 10


def situacao_por_datas(edital: EditalExtraido, referencia: date) -> str:
    if edital.inscricao_fim is not None and referencia <= edital.inscricao_fim:
        return "INSCRICOES_ABERTAS"
    return "EM_ANDAMENTO"


def executar_estruturacao(repo: Repositorio, ia: ExtratorIA | None = None) -> ResumoEtapa:
    """Regras da banca primeiro; a IA (se configurada) só entra quando a banca não tem extrator ou faltaram dados
    principais (cargos/vagas, inscrições, taxa, isenção). Cada edital vai à IA no máximo uma vez (cache)."""
    inicio = agora()
    dia = hoje()
    pendentes = repo.concursos_para_estruturar()
    repo.conn.commit()
    estruturados = 0
    usos_ia = 0
    falhas: list[str] = []
    for numero, concurso in enumerate(pendentes, start=1):
        texto = concurso["texto_extraido"] or ""
        extrator = extrator_para_banca(concurso["banca"])
        try:
            regras = extrator.extrair(texto) if extrator else None
            edital = regras
            if ia is not None and precisa_de_ia(regras):
                resultado = ia.extrair(texto, concurso["hash_sha256"], dia)
                usos_ia += resultado.origem not in ("cache", "triagem", "falha")
                if resultado.edital is not None:
                    edital = combinar(regras, resultado.edital)
                    log.info("concurso %d: IA (%s) completou a leitura", concurso["id"], resultado.origem)
                elif resultado.motivo:
                    log.info("concurso %d: sem IA (%s: %s)", concurso["id"], resultado.origem, resultado.motivo)
            if edital is None:
                continue
            repo.aplicar_edital(concurso["id"], concurso["documento_id"], edital, situacao_por_datas(edital, dia))
            if concurso.get("orgao_id") is None and edital.orgao:
                orgao = inferir_orgao(edital.orgao)
                if orgao is not None:
                    repo.definir_orgao_se_ausente(concurso["id"], orgao)
            estruturados += 1
            log.info(
                "[%d/%d] concurso %d estruturado: %d cargos, avisos=%s",
                numero,
                len(pendentes),
                concurso["id"],
                len(edital.cargos),
                list(edital.avisos) or "-",
            )
        except Exception as erro:
            log.exception("falha ao estruturar o concurso %d", concurso["id"])
            falhas.append(f"concurso {concurso['id']}: {erro}")
    if ia is not None:
        log.info("estruturação: %d editais pendentes, %d chamadas novas de IA", len(pendentes), usos_ia)

    alterados = repo.atualizar_situacoes_por_data(hoje(), DIAS_FORA_DA_LISTA_PARA_ENCERRAR)
    if alterados:
        log.info("%d concursos mudaram de situação pela data/ausência na fonte", alterados)
    status = "SUCESSO" if not falhas else ("FALHA" if estruturados == 0 else "PARCIAL")
    mensagem = "; ".join(falhas[:10]) or None
    repo.registrar_execucao("ESTRUTURACAO", inicio, status, estruturados, mensagem)
    return ResumoEtapa("ESTRUTURACAO", status, estruturados, mensagem)
