"""E-mail diário ao administrador (no máximo um por dia, só quando há algo a mostrar), com o código `NQ-<id>` de cada
concurso:

1. novos concursos que a busca na web encontrou nas últimas 24 h;
2. concursos abertos que aguardam o edital (o coletor não conseguiu baixar);
3. concursos no site com dados faltando (quais campos).

Para 2 e 3, o administrador baixa no navegador o edital e o que mais houver (cronograma, retificação, quadro de
vagas) e põe na pasta do Drive com o código no nome (`NQ-123 edital.pdf`, `NQ-123 cronograma.pdf`). A importação
seguinte liga os arquivos ao concurso e o relê.
"""

from __future__ import annotations

import logging
import smtplib
from collections.abc import Sequence
from datetime import date, datetime, time

from coletor.db import Linha, Repositorio
from coletor.ia.email_relatorio import ConfigEmail, enviar, montar_mensagem
from coletor.importacao_manual import codigo_do_concurso
from coletor.pipeline.comum import FUSO, ResumoEtapa, agora, hoje

log = logging.getLogger(__name__)

_SITUACAO = {"PREVISTO": "previsto", "INSCRICOES_ABERTAS": "inscrições abertas", "EM_ANDAMENTO": "em andamento"}


def _cabecalho(linha: Linha) -> str:
    prazo = f" — inscrições até {linha['inscricao_fim']:%d/%m/%Y}" if linha.get("inscricao_fim") else ""
    banca = f" ({linha['banca']})" if linha.get("banca") else ""
    return f"{codigo_do_concurso(linha['id'])} — {linha['orgao']}{banca}{prazo}"


def montar_email(
    novos: Sequence[Linha], aguardando: Sequence[Linha], faltando: Sequence[Linha], dia: date
) -> tuple[str, str]:
    assunto = (
        f"NqnTech {dia:%d/%m/%Y}: {len(novos)} novo(s), {len(aguardando)} aguardando edital, "
        f"{len(faltando)} com dados faltando"
    )
    partes = [
        "Como completar: baixe no navegador o edital e o que mais houver (cronograma, retificação, quadro de vagas)",
        'e ponha na pasta do Drive com o código no nome: "NQ-123 edital.pdf", "NQ-123 cronograma.pdf",',
        '"NQ-123 retificacao.pdf". A próxima execução do coletor (4x/dia) liga os arquivos ao concurso e o relê.',
        "",
    ]
    if novos:
        partes += [f"== 1. Novos encontrados pela busca na web ({len(novos)}) ==", ""]
        for linha in novos:
            no_site = "no site" if linha["publicado"] else "ainda fora do site"
            partes += [f"{_cabecalho(linha)} [{_SITUACAO.get(linha['situacao'], linha['situacao'])}, {no_site}]",
                       f"  Página: {linha['link_oficial']}", ""]  # fmt: skip
    if aguardando:
        partes += [f"== 2. Aguardando edital ({len(aguardando)}) — só entram no site depois do edital ==", ""]
        for linha in aguardando:
            partes.append(_cabecalho(linha))
            partes.append(f"  Página: {linha['link_oficial']}")
            if linha["link_edital"]:
                partes.append(f"  PDF indicado pela busca: {linha['link_edital']}")
            if linha["edital_falha"]:
                partes.append(f"  Por que não baixou: {linha['edital_falha']}")
            partes.append("")
    if faltando:
        partes += [f"== 3. No site com dados faltando ({len(faltando)}) ==", ""]
        for linha in faltando:
            partes += [_cabecalho(linha), f"  Falta: {', '.join(linha['faltam'])}",
                       f"  Página: {linha['link_oficial']}", ""]  # fmt: skip
    return assunto, "\n".join(partes)


def enviar_pendencias(repo: Repositorio, config: ConfigEmail | None) -> ResumoEtapa:
    inicio = agora()
    dia = hoje()
    if repo.ja_executou_hoje("PENDENCIAS", datetime.combine(dia, time.min, tzinfo=FUSO)):
        return ResumoEtapa("PENDENCIAS", "SUCESSO", 0, "já enviado hoje")
    novos, aguardando, faltando = repo.novos_da_busca(), repo.aguardando_edital(), repo.dados_faltando()
    repo.conn.commit()
    total = len(novos) + len(aguardando) + len(faltando)
    if not total:
        log.info("pendências: nada a informar")
        return ResumoEtapa("PENDENCIAS", "SUCESSO", 0)
    assunto, corpo = montar_email(novos, aguardando, faltando, dia)
    if config is None:
        log.info("pendências (e-mail não configurado): %s\n%s", assunto, corpo)
        return ResumoEtapa("PENDENCIAS", "SUCESSO", 0, "e-mail não configurado")
    try:
        enviar(config, montar_mensagem(config, assunto, corpo))
    except (OSError, smtplib.SMTPException) as erro:
        log.error("pendências não enviadas: %s", erro)
        return ResumoEtapa("PENDENCIAS", "PARCIAL", 0, f"e-mail não enviado: {erro}")
    repo.registrar_execucao("PENDENCIAS", inicio, "SUCESSO", total, None)
    return ResumoEtapa("PENDENCIAS", "SUCESSO", total)
