"""Etapa 4: texto do edital mais recente → campos do concurso, quadro de cargos e avisos de extração.

Roda sobre o texto já gravado (o PDF não existe mais), por isso pode ser repetida a qualquer momento:
um extrator melhorado reprocessa tudo zerando concurso.edital_documento_id.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from typing import Any

from coletor.classificacao.orgao import OrgaoInferido, inferir_orgao
from coletor.db import Repositorio
from coletor.extratores import extrator_para_banca
from coletor.extratores.base import EditalExtraido
from coletor.extratores.secoes import Isencoes, calendario
from coletor.extratores.secoes import extrair_isencoes as isencoes_por_regras
from coletor.ia.extrator import ExtratorIA, combinar, precisa_de_ia
from coletor.ia.lacunas import faltando
from coletor.pipeline.comum import ResumoEtapa, agora, hoje
from coletor.precadastro import completar_com_busca

log = logging.getLogger(__name__)

DIAS_FORA_DA_LISTA_PARA_ENCERRAR = 10
# Bancas que declaram Content-Signal ai-train=no: o texto delas não vai a provedores de IA (só regras), venha o PDF
# da coleta ou da importação manual.
BANCAS_SEM_IA = frozenset({"IDECAN"})


def orgao_do_edital(edital: EditalExtraido) -> OrgaoInferido | None:
    """Órgão do edital: a inferência pelo nome, completada pelo local que a IA leu (esfera, UF, município)."""
    if not edital.orgao:
        return None
    inferido = inferir_orgao(edital.orgao)
    if inferido is None and not (edital.esfera or edital.uf):
        return None
    return OrgaoInferido(
        nome=inferido.nome if inferido else edital.orgao,
        esfera=(inferido.esfera if inferido else None) or edital.esfera,
        uf=(inferido.uf if inferido else None) or (None if edital.esfera == "FEDERAL" else edital.uf),
        municipio=(inferido.municipio if inferido else None) or edital.municipio,
    )


def completar_com_complemento(
    edital: EditalExtraido, complemento: Mapping[str, Any], ia: ExtratorIA | None, dia: date
) -> EditalExtraido:
    """Cronograma, retificação ou anexo enviado pelo Drive: só preenche o que o edital não trouxe (calendário e
    isenção pelas regras comuns; inscrição, prova, salário e prazo de isenção pela leitura dirigida da IA)."""
    texto = str(complemento.get("texto") or "")
    if not texto:
        return edital
    if not edital.isencoes:
        isencoes = isencoes_por_regras(texto)
        if isencoes.tipos:
            edital = replace(edital, isencoes=isencoes.tipos, isencao_inicio=isencoes.inicio,
                             isencao_fim=isencoes.fim)  # fmt: skip
    if ia is not None and faltando(edital):
        edital = ia.completar(edital, texto, complemento.get("hash"), dia)
    if not any(e.inicio for e in edital.eventos):
        periodo = Isencoes(edital.isencoes, edital.isencao_inicio, edital.isencao_fim)
        eventos = calendario(texto, periodo, (edital.inscricao_inicio, edital.inscricao_fim), edital.data_prova)
        if any(e.inicio for e in eventos):
            edital = replace(edital, eventos=eventos)
    return edital


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
            if ia is not None and concurso["banca"] not in BANCAS_SEM_IA and precisa_de_ia(regras):
                resultado = ia.extrair(texto, concurso["hash_sha256"], dia)
                usos_ia += resultado.origem not in ("cache", "triagem", "falha")
                if resultado.edital is not None:
                    edital = combinar(regras, resultado.edital)
                    log.info("concurso %d: IA (%s) completou a leitura", concurso["id"], resultado.origem)
                elif resultado.motivo:
                    log.info("concurso %d: sem IA (%s: %s)", concurso["id"], resultado.origem, resultado.motivo)
            if edital is None:
                continue
            if ia is not None and concurso["banca"] not in BANCAS_SEM_IA and faltando(edital):
                edital = ia.completar(edital, texto, concurso["hash_sha256"], dia)
            sem_ia = ia is None or concurso["banca"] in BANCAS_SEM_IA
            for complemento in concurso.get("complementos") or ():
                edital = completar_com_complemento(edital, complemento, None if sem_ia else ia, dia)
            edital = completar_com_busca(edital, concurso.get("dados_busca"), concurso["id"])
            repo.aplicar_edital(concurso["id"], concurso["documento_id"], edital, situacao_por_datas(edital, dia))
            orgao = orgao_do_edital(edital)
            if orgao is not None and concurso.get("orgao_id") is None:
                repo.definir_orgao_se_ausente(concurso["id"], orgao)
            elif orgao is not None and orgao.uf and not concurso.get("orgao_uf") and edital.esfera != "FEDERAL":
                repo.trocar_orgao(concurso["id"], orgao)
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
