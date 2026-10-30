"""Etapa 1: cada fonte ativa com adaptador → sinal_descoberta (sem duplicar) + execucao_coleta."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

from coletor.db import Repositorio
from coletor.fontes.base import Fonte
from coletor.http_cliente import ClienteHttp
from coletor.pipeline.comum import DIAS_FOLGA_INSCRICAO, DIAS_RELEITURA, ResumoEtapa, agora, hoje, status_por_falhas

log = logging.getLogger(__name__)


def executar_descoberta(
    repo: Repositorio,
    fontes: Mapping[str, Fonte],
    criar_http: Callable[[frozenset[str]], ClienteHttp],
    somente: str | None = None,
    dry_run: bool = False,
) -> list[ResumoEtapa]:
    resumos: list[ResumoEtapa] = []
    for cadastrada in repo.fontes_ativas():
        if somente and cadastrada.nome != somente:
            continue
        fonte = fontes.get(cadastrada.nome)
        if fonte is None:
            log.info("fonte '%s' ativa no banco, mas ainda sem adaptador; ignorada", cadastrada.nome)
            continue

        inicio = agora()
        pular = repo.urls_sem_oportunidade(cadastrada.id, hoje(), DIAS_FOLGA_INSCRICAO, DIAS_RELEITURA)
        try:
            with criar_http(fonte.dominios) as http:
                resultado = fonte.descobrir(http, pular)
        except Exception as erro:  # uma fonte quebrada não pode derrubar as outras
            log.exception("fonte '%s' falhou", cadastrada.nome)
            if not dry_run:
                repo.retomar_conexao()
                repo.registrar_execucao(
                    "DESCOBERTA", inicio, "FALHA", 0, f"{type(erro).__name__}: {erro}", cadastrada.id
                )
            resumos.append(ResumoEtapa("DESCOBERTA", "FALHA", 0, str(erro), cadastrada.nome))
            continue

        if dry_run:
            for sinal in resultado.sinais:
                log.info(
                    "[dry-run] %s | %s | %d arquivos", sinal.titulo, sinal.url, len(sinal.payload.get("arquivos", []))
                )
            resumos.append(ResumoEtapa("DESCOBERTA", "SUCESSO", len(resultado.sinais), None, cadastrada.nome))
            continue

        repo.retomar_conexao()
        with repo.transacao():
            novos = sum(repo.gravar_sinal(cadastrada.id, sinal) for sinal in resultado.sinais)
        status = status_por_falhas(resultado.falhas, len(resultado.sinais))
        mensagem = "; ".join(resultado.falhas[:10]) or None
        repo.registrar_execucao("DESCOBERTA", inicio, status, novos, mensagem, cadastrada.id)
        log.info(
            "fonte '%s': %d sinais (%d novos), %d falhas",
            cadastrada.nome,
            len(resultado.sinais),
            novos,
            len(resultado.falhas),
        )
        resumos.append(ResumoEtapa("DESCOBERTA", status, novos, mensagem, cadastrada.nome))
    return resumos
