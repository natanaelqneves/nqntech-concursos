"""Linha de comando do coletor.

python -m coletor executar                 # todas as etapas (o que o GitHub Actions roda)
python -m coletor descobrir --fonte fgv --dry-run
python -m coletor documentos --limite 5
python -m coletor classificar             # reaplica config/areas.yml etc. sem coletar nada
python -m coletor resumir                 # refaz resumos, slugs e publicação sem coletar nada
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from coletor.config import ConfigInvalida, carregar_config, resolver_caminho
from coletor.db import Repositorio, conectar
from coletor.pipeline.comum import ResumoEtapa
from coletor.pipeline.orquestrador import ETAPAS, Orquestrador, codigo_de_saida

log = logging.getLogger("coletor")


def configurar_logs(verboso: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pdfminer").setLevel(logging.ERROR)


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m coletor", description="Coletor do NqnTech Concursos")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="comando", required=True)

    executar = sub.add_parser("executar", help="todas as etapas em sequência")
    executar.add_argument("--fonte")
    executar.add_argument("--limite", type=int, help="máximo de documentos baixados nesta execução")

    descobrir = sub.add_parser("descobrir", help="etapa 1: fontes → sinais")
    descobrir.add_argument("--fonte")
    descobrir.add_argument("--dry-run", action="store_true", help="só mostra o que encontraria; não grava nada")

    sub.add_parser("vincular", help="etapa 2: sinais → concursos e documentos")
    documentos = sub.add_parser("documentos", help="etapas 3-4: baixar (temporário) e extrair texto")
    documentos.add_argument("--limite", type=int)
    sub.add_parser("estruturar", help="etapa 4: texto do edital → cargos, datas e taxas")
    sub.add_parser("classificar", help="etapa 5: área e escolaridade dos cargos, local do concurso e CNU")
    sub.add_parser("resumir", help="etapa 6: resumo, slug, campos do site e publicação")
    return parser


def anotar_github(resumos: list[ResumoEtapa]) -> None:
    """No GitHub Actions, falhas viram anotações visíveis no resumo da execução."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    for resumo in resumos:
        if resumo.status == "SUCESSO":
            continue
        nivel = "error" if resumo.status == "FALHA" else "warning"
        alvo = f" ({resumo.fonte})" if resumo.fonte else ""
        mensagem = (resumo.mensagem or "").replace("\n", " ")[:900]
        print(f"::{nivel} title=Coletor {resumo.etapa}{alvo}::{resumo.status}: {mensagem}")


def main(argv: list[str] | None = None) -> int:
    args = criar_parser().parse_args(argv)
    configurar_logs(args.verbose)
    env_local = resolver_caminho(".env")
    if env_local.exists():
        load_dotenv(env_local, override=False)  # variáveis já definidas (GitHub Secrets) têm prioridade

    try:
        config = carregar_config()
    except ConfigInvalida as erro:
        log.error("configuração inválida: %s", erro)
        anotar_github([ResumoEtapa("CONFIGURACAO", "FALHA", 0, str(erro))])
        return 2

    etapas = (
        ETAPAS
        if args.comando == "executar"
        else {
            "descobrir": ("descobrir",),
            "vincular": ("vincular",),
            "documentos": ("documentos",),
            "estruturar": ("estruturar",),
            "classificar": ("classificar",),
            "resumir": ("resumir",),
        }[args.comando]
    )

    try:
        conn = conectar(config.banco)
    except Exception as erro:
        log.error("sem conexão com o banco: %s", erro)
        anotar_github([ResumoEtapa("CONEXAO", "FALHA", 0, str(erro))])
        return 1

    resumos: list[ResumoEtapa] = []
    try:
        with Repositorio(conn, reconectar=lambda: conectar(config.banco)) as repo:
            orquestrador = Orquestrador(config, repo)
            resumos = orquestrador.executar(
                etapas,
                fonte=getattr(args, "fonte", None),
                dry_run=getattr(args, "dry_run", False),
                limite_documentos=getattr(args, "limite", None),
            )
    except Exception as erro:
        # Falha fora de qualquer etapa (ex.: a conexão caiu e nem o rollback funcionou): sem isto, o GitHub Actions
        # só mostraria "exit code 1", sem dizer o que houve.
        log.exception("coletor interrompido")
        anotar_github([*resumos, ResumoEtapa("GERAL", "FALHA", 0, f"{type(erro).__name__}: {erro}")])
        return 1

    for resumo in resumos:
        log.info(
            "resumo %-13s %-8s itens=%d%s",
            resumo.etapa,
            resumo.status,
            resumo.itens_novos,
            f" fonte={resumo.fonte}" if resumo.fonte else "",
        )
    anotar_github(resumos)
    return codigo_de_saida(resumos)


if __name__ == "__main__":
    sys.exit(main())
