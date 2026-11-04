"""Linha de comando do coletor.

python -m coletor executar                 # todas as etapas (o que o GitHub Actions roda)
python -m coletor descobrir --fonte fgv --dry-run
python -m coletor documentos --limite 5
python -m coletor classificar             # reaplica config/areas.yml etc. sem coletar nada
python -m coletor resumir                 # refaz resumos, slugs e publicação sem coletar nada
python -m coletor importar-pdfs PASTA --banca FCC [--link https://...]   # PDFs baixados à mão
python -m coletor buscar-concursos [--bancas FCC VUNESP] [--saida pasta]  # sugestões pela Busca Google (Gemini)
"""

from __future__ import annotations

import argparse
import logging
import os
import smtplib
import sys
from pathlib import Path

from dotenv import load_dotenv

from coletor.config import ConfigInvalida, carregar_config, resolver_caminho
from coletor.db import Repositorio, conectar
from coletor.importacao_manual import ImportacaoInvalida, importar_pasta
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
    buscar = sub.add_parser("buscar-concursos", help="sugere concursos abertos das bancas sem coleta (Gemini + Busca)")
    buscar.add_argument("--bancas", nargs="+", help="siglas (padrão: todas as bancas sem coleta automática)")
    buscar.add_argument("--saida", default="buscas", help="pasta dos relatórios .md e .csv (padrão: buscas)")
    buscar.add_argument("--email", action="store_true", help="envia o relatório para BUSCA_EMAIL_DESTINO (SMTP_*)")
    importar = sub.add_parser("importar-pdfs", help="lê PDFs de uma pasta local e aplica as etapas 4 a 6")
    importar.add_argument("pasta", help="pasta com os PDFs (opcional: <nome>.url com o link oficial de cada um)")
    importar.add_argument("--banca", required=True, help="sigla da banca (FCC, VUNESP, CESGRANRIO... ou OUTRA)")
    importar.add_argument("--link", help="link oficial do concurso para os PDFs sem arquivo .url")
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


def buscar_concursos(args: argparse.Namespace) -> int:
    """Não usa o banco: só a chave do Gemini. O resultado é um relatório para conferência humana."""
    import httpx

    from coletor.ia.busca_web import DOMINIOS_BANCAS, buscar_bancas, criar_buscadores, gravar
    from coletor.ia.email_relatorio import ConfigEmail, EmailNaoConfigurado, enviar, montar_mensagem
    from coletor.pipeline.comum import hoje

    config_email = None
    if args.email:
        try:
            config_email = ConfigEmail.do_ambiente(os.environ)
        except EmailNaoConfigurado as erro:
            log.error("e-mail: %s", erro)
            return 2
    bancas = [b.upper() for b in (args.bancas or DOMINIOS_BANCAS)]
    with httpx.Client(timeout=180) as http:
        buscadores = criar_buscadores(os.environ, http)
        if not buscadores:
            log.error("defina GEMINI_API_KEY e/ou OPENROUTER_API_KEY (a busca usa a Busca Google do Gemini)")
            return 2
        log.info("buscadores na ordem: %s", [b.nome for b in buscadores])
        sugestoes, falhas = buscar_bancas(buscadores, bancas, hoje())
    csv_, md = gravar(sugestoes, Path(args.saida), hoje(), falhas)
    for falha in falhas:
        log.warning("%s", falha)
    log.info("%d sugestões (%d oficiais). Relatórios: %s e %s", len(sugestoes),
             sum(s.oficial for s in sugestoes), md, csv_)  # fmt: skip
    if config_email is not None:
        oficiais = sum(s.oficial for s in sugestoes)
        assunto = f"Concursos sugeridos {hoje():%d/%m/%Y}: {len(sugestoes)} ({oficiais} em sites oficiais)"
        if falhas:
            assunto += f" – {len(falhas)} falha(s)"
        try:
            enviar(config_email, montar_mensagem(config_email, assunto, md, csv_))
        except (OSError, smtplib.SMTPException) as erro:
            log.error("e-mail não enviado: %s", erro)
            return 1
    return 0 if sugestoes or not falhas else 1


def main(argv: list[str] | None = None) -> int:
    args = criar_parser().parse_args(argv)
    configurar_logs(args.verbose)
    env_local = resolver_caminho(".env")
    if env_local.exists():
        load_dotenv(env_local, override=False)  # variáveis já definidas (GitHub Secrets) têm prioridade

    if args.comando == "buscar-concursos":
        return buscar_concursos(args)

    try:
        config = carregar_config()
    except ConfigInvalida as erro:
        log.error("configuração inválida: %s", erro)
        anotar_github([ResumoEtapa("CONFIGURACAO", "FALHA", 0, str(erro))])
        return 2

    importacao = args.comando == "importar-pdfs"
    etapas = (
        ("estruturar", "classificar", "resumir")
        if importacao
        else ETAPAS
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
            if importacao:
                try:
                    resumos.append(importar_pasta(repo, Path(args.pasta), args.banca, args.link, config.pdf_max_bytes))
                except ImportacaoInvalida as erro:
                    log.error("%s", erro)
                    return 2
            resumos += orquestrador.executar(
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
