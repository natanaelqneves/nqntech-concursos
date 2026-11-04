"""Executa as etapas na ordem certa e decide o código de saída do processo."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager

import httpx

from coletor.classificacao.regras import PASTA_CONFIG
from coletor.config import Config, resolver_caminho
from coletor.db import Repositorio
from coletor.fontes import Fonte, fontes_disponiveis
from coletor.fontes.busca_ia import AgendaBusca, FonteBuscaIA
from coletor.http_cliente import ClienteHttp
from coletor.ia import ExtratorIA, criar_provedores
from coletor.ia.busca_web import AlvoBusca, Buscador, ResultadoAlvo, carregar_alvos, criar_buscadores
from coletor.ia.provedores import Rodizio
from coletor.pipeline.classificacao import executar_classificacao
from coletor.pipeline.comum import ResumoEtapa, agora, hoje
from coletor.pipeline.descoberta import executar_descoberta
from coletor.pipeline.documentos import executar_documentos
from coletor.pipeline.estruturacao import executar_estruturacao
from coletor.pipeline.localizacao import executar_localizacao
from coletor.pipeline.resumo import executar_resumo
from coletor.pipeline.vinculacao import executar_vinculacao

log = logging.getLogger(__name__)

# Fluxo único (seção 6): fontes (busca na web e sites das bancas) → pré-cadastro → edital (localizar e baixar, ou
# Drive) → leitura do edital confere/completa → classificação → resumo e publicação.
ETAPAS = ("descobrir", "vincular", "localizar", "documentos", "estruturar", "classificar", "resumir")


class Orquestrador:
    def __init__(
        self,
        config: Config,
        repo: Repositorio,
        criar_http: Callable[[frozenset[str]], ClienteHttp] | None = None,
    ) -> None:
        self._config = config
        self._repo = repo
        self._fontes: dict[str, Fonte] = dict(
            fontes_disponiveis(config.max_paginas_listagem, config.max_paginas_realizados)
        )
        self._criar_http = criar_http or self._http_padrao
        self._alvos = carregar_alvos(resolver_caminho(f"{PASTA_CONFIG}/busca.yml"))
        if config.ia.gemini_chave or config.ia.openrouter_chave:
            self._fontes[FonteBuscaIA.nome] = self._fonte_busca(self._alvos)
        else:
            log.info("busca na web desligada (sem GEMINI_API_KEY nem OPENROUTER_API_KEY)")

    def _fonte_busca(self, alvos: Sequence[AlvoBusca]) -> FonteBuscaIA:
        repo, config = self._repo, self._config.busca

        def buscadores() -> tuple[Sequence[Buscador], Callable[[], None]]:
            http = httpx.Client(timeout=180)
            return criar_buscadores(os.environ, http), http.close

        def registrar(resultado: ResultadoAlvo) -> None:
            repo.retomar_conexao()
            repo.registrar_busca_alvo(resultado.alvo.codigo, len(resultado.sugestoes), resultado.erro)

        agenda = AgendaBusca(lambda codigos: repo.alvos_vencidos(codigos, config.intervalo_h), registrar)
        return FonteBuscaIA(buscadores, alvos, agenda, hoje, config.max_alvos)

    def _dominios_banca(self, sigla: str | None) -> tuple[str, ...]:
        return next((a.dominios for a in self._alvos if sigla and a.banca == sigla), ())

    @contextmanager
    def _extrator_ia(self) -> Iterator[ExtratorIA | None]:
        if not self._config.ia.ativa:
            yield None
            return
        config = self._config.ia
        with httpx.Client(timeout=config.timeout_s) as http:
            provedores = criar_provedores(config, http)
            log.info("IA ativa: %s (teto de %d chamadas nesta execução)", [p.nome for p in provedores],
                     config.max_chamadas)  # fmt: skip
            rodizio = Rodizio(provedores, config.max_chamadas, config.intervalo_s)
            yield ExtratorIA(rodizio, self._repo.ler_cache_ia, self._repo.gravar_cache_ia, config.max_caracteres)

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
            case "localizar":
                busca = self._config.busca
                return [
                    executar_localizacao(
                        self._repo,
                        self._criar_http,
                        self._dominios_banca,
                        busca.max_localizar,
                        busca.intervalo_localizar_h,
                    )
                ]
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
                with self._extrator_ia() as ia:
                    return [executar_estruturacao(self._repo, ia)]
            case "classificar":
                return [executar_classificacao(self._repo)]
            case "resumir":
                return [executar_resumo(self._repo)]
        raise ValueError(f"etapa desconhecida: {etapa}")


def codigo_de_saida(resumos: list[ResumoEtapa]) -> int:
    """0 = tudo certo ou falhas parciais; 1 = alguma etapa falhou por inteiro (o GitHub Actions marca vermelho)."""
    return 1 if any(r.status == "FALHA" for r in resumos) else 0
