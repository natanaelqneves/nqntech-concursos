"""Envio do relatório da busca assistida por e-mail (SMTP com STARTTLS; ex.: Gmail com senha de app)."""

from __future__ import annotations

import logging
import smtplib
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger(__name__)


class EmailNaoConfigurado(Exception):
    pass


@dataclass(frozen=True)
class ConfigEmail:
    host: str
    porta: int
    usuario: str
    senha: str
    destino: str

    @classmethod
    def do_ambiente(cls, env: Mapping[str, str]) -> ConfigEmail:
        faltando = [n for n in ("SMTP_USUARIO", "SMTP_SENHA", "BUSCA_EMAIL_DESTINO") if not env.get(n)]
        if faltando:
            raise EmailNaoConfigurado("faltam as variáveis " + ", ".join(faltando))
        return cls(env.get("SMTP_HOST") or "smtp.gmail.com", int(env.get("SMTP_PORTA") or 587), env["SMTP_USUARIO"],
                   env["SMTP_SENHA"], env["BUSCA_EMAIL_DESTINO"])  # fmt: skip

    def __repr__(self) -> str:  # senha nunca em logs
        return f"ConfigEmail(host={self.host!r}, porta={self.porta}, usuario={self.usuario!r})"


def montar_mensagem(config: ConfigEmail, assunto: str, markdown: Path, csv: Path) -> EmailMessage:
    mensagem = EmailMessage()
    mensagem["Subject"] = assunto
    mensagem["From"] = config.usuario
    mensagem["To"] = config.destino
    mensagem.set_content(markdown.read_text(encoding="utf-8"))
    mensagem.add_attachment(csv.read_bytes(), maintype="text", subtype="csv", filename=csv.name)
    return mensagem


def enviar(config: ConfigEmail, mensagem: EmailMessage) -> None:
    with smtplib.SMTP(config.host, config.porta, timeout=60) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(config.usuario, config.senha)
        smtp.send_message(mensagem)
    log.info("relatório enviado por e-mail")
