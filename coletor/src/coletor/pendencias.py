"""E-mail diário ao administrador com os concursos abertos que aguardam o edital (o coletor não conseguiu baixar).

Para cada um vai o código ("NQ-123"): o administrador baixa o PDF no navegador e o põe na pasta do Drive com o código
no nome; a importação seguinte liga o arquivo ao concurso. Sai no máximo uma vez por dia e só quando há pendências.
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


def montar_pendencias(linhas: Sequence[Linha], dia: date) -> tuple[str, str]:
    assunto = f"NqnTech: {len(linhas)} concurso(s) aguardando edital ({dia:%d/%m/%Y})"
    partes = [
        f"{len(linhas)} concurso(s) com inscrições abertas ainda sem edital lido. Eles só aparecem no site depois do",
        "edital. Baixe o PDF no navegador e envie para a pasta do Drive com o código no nome do arquivo",
        '(ex.: "NQ-123 edital.pdf"). A próxima execução do coletor liga o arquivo ao concurso.',
        "",
    ]
    for linha in linhas:
        prazo = f" — inscrições até {linha['inscricao_fim']:%d/%m/%Y}" if linha["inscricao_fim"] else ""
        banca = f" ({linha['banca']})" if linha["banca"] else ""
        partes.append(f"{codigo_do_concurso(linha['id'])} — {linha['orgao']}{banca}{prazo}")
        partes.append(f"  Página: {linha['link_oficial']}")
        if linha["link_edital"]:
            partes.append(f"  PDF indicado pela busca: {linha['link_edital']}")
        if linha["edital_falha"]:
            partes.append(f"  Por que não baixou: {linha['edital_falha']}")
        partes.append("")
    return assunto, "\n".join(partes)


def enviar_pendencias(repo: Repositorio, config: ConfigEmail | None) -> ResumoEtapa:
    inicio = agora()
    dia = hoje()
    if repo.ja_executou_hoje("PENDENCIAS", datetime.combine(dia, time.min, tzinfo=FUSO)):
        return ResumoEtapa("PENDENCIAS", "SUCESSO", 0, "já enviado hoje")
    linhas = repo.aguardando_edital()
    repo.conn.commit()
    if not linhas:
        log.info("pendências: nenhum concurso aguardando edital")
        return ResumoEtapa("PENDENCIAS", "SUCESSO", 0)
    assunto, corpo = montar_pendencias(linhas, dia)
    if config is None:
        log.info("pendências (e-mail não configurado):\n%s", corpo)
        return ResumoEtapa("PENDENCIAS", "SUCESSO", 0, "e-mail não configurado")
    try:
        enviar(config, montar_mensagem(config, assunto, corpo))
    except (OSError, smtplib.SMTPException) as erro:
        log.error("pendências não enviadas: %s", erro)
        return ResumoEtapa("PENDENCIAS", "PARCIAL", 0, f"e-mail não enviado: {erro}")
    repo.registrar_execucao("PENDENCIAS", inicio, "SUCESSO", len(linhas), None)
    return ResumoEtapa("PENDENCIAS", "SUCESSO", len(linhas))
