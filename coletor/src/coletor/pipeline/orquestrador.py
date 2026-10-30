"""Executa as etapas na ordem certa e decide o código de saída do processo."""

from __future__ import annotations

import logging
from collections.abc import Callable

from coletor.config import Config
from coletor.db import Repositorio
from coletor.fontes import fontes_disponiveis
from coletor.http_cliente import ClienteHttp
from coletor.pipeline.classificacao import executar_classificacao
from coletor.pipeline.comum import ResumoEtapa, agora
from coletor.pipeline.descoberta import executar_descoberta
from coletor.pipeline.documentos import executar_documentos
from coletor.pipeline.estruturacao import executar_estruturacao
from coletor.pipeline.resumo import executar_resumo
from coletor.pipeline.vinculacao import executar_vinculacao

log = logging.getLogger(__name__)

ETAPAS = ("descobrir", "vincular", "documentos", "estruturar", "classificar", "resumir")


class Orquestrador:
    def __init__(
        self,
        config: Config,
        repo: Repositorio,
        criar_http: Callable[[frozenset[str]], ClienteHttp] | None = None,
    ) -> None:
        self._config = config
        self._repo = repo
        self._fontes = fontes_disponiveis(config.max_paginas_listagem, config.max_paginas_realizados)
        self._criar_http = criar_http or self._http_padrao

    def _http_padrao(self, dominios: frozenset[str]) -> ClienteHttp:
        return ClienteHttp(dominios, self._config.user_agent, intervalo_s=self._config.intervalo_dominio_s)

    def executar(
        self,
        etapas: tuple[str, ...],
        fonte: str | None = None,
        dry_run: bool = False,
        limite_documentos: int | None = None,
    ) -> list[ResumoEtapa]:
        resumos: list[ResumoEtapa] = []
        for etapa in etapas:
            if dry_run and etapa != "descobrir":
                continue
            try:
                resumos.extend(self._executar_etapa(etapa, fonte, dry_run, limite_documentos))
            except Exception as erro:
                # Falha inesperada numa etapa não impede as seguintes (ex.: estruturar o que já foi lido).
                log.exception("etapa '%s' falhou", etapa)
                resumos.append(ResumoEtapa(etapa.upper(), "FALHA", 0, f"{type(erro).__name__}: {erro}"))
                try:
                    self._repo.conn.rollback()
                except Exception:
                    log.exception("rollback falhou depois da etapa '%s' (conexão perdida?)", etapa)
                    break
                try:
                    self._repo.registrar_execucao("GERAL", agora(), "FALHA", 0, f"etapa {etapa}: {erro}")
                except Exception:
                    log.exception("não foi possível registrar a falha no banco")
        return resumos

    def _executar_etapa(self, etapa: str, fonte: str | None, dry_run: bool, limite: int | None) -> list[ResumoEtapa]:
        match etapa:
            case "descobrir":
                return executar_descoberta(self._repo, self._fontes, self._criar_http, fonte, dry_run)
            case "vincular":
                return [executar_vinculacao(self._repo)]
            case "documentos":
                dominios = frozenset().union(*(f.dominios for f in self._fontes.values()))
                return [
                    executar_documentos(
                        self._repo,
                        self._criar_http,
                        dominios,
                        limite or self._config.max_documentos_por_execucao,
                        self._config.pdf_max_bytes,
                    )
                ]
            case "estruturar":
                return [executar_estruturacao(self._repo)]
            case "classificar":
                return [executar_classificacao(self._repo)]
            case "resumir":
                return [executar_resumo(self._repo)]
        raise ValueError(f"etapa desconhecida: {etapa}")


def codigo_de_saida(resumos: list[ResumoEtapa]) -> int:
    """0 = tudo certo ou falhas parciais; 1 = alguma etapa falhou por inteiro (o GitHub Actions marca vermelho)."""
    return 1 if any(r.status == "FALHA" for r in resumos) else 0
