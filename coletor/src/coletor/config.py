from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Só vale com instalação editável (pip install -e): instalado no site-packages, __file__ aponta para lá.
_RAIZ_CODIGO_FONTE = Path(__file__).resolve().parents[3]


def resolver_caminho(relativo: str) -> Path:
    """Caminho relativo procurado no diretório atual (como no GitHub Actions) e, em dev, na raiz do repositório."""
    caminho = Path(relativo)
    if caminho.is_absolute():
        return caminho
    for base in (Path.cwd(), _RAIZ_CODIGO_FONTE):
        if (base / caminho).exists():
            return base / caminho
    return Path.cwd() / caminho


SSLMODES_VALIDOS = frozenset({"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})


class ConfigInvalida(Exception):
    pass


@dataclass(frozen=True)
class ConfigBanco:
    host: str
    porta: int
    nome: str
    usuario: str
    senha: str
    sslmode: str

    def parametros(self) -> dict[str, str | int]:
        return {
            "host": self.host,
            "port": self.porta,
            "dbname": self.nome,
            "user": self.usuario,
            "password": self.senha,
            "sslmode": self.sslmode,
            "application_name": "nqntech-coletor",
            # O Neon desliga o processamento ocioso; a primeira conexão do dia pode levar alguns segundos.
            "connect_timeout": 20,
        }

    def __repr__(self) -> str:  # nunca expor a senha em logs/tracebacks
        return f"ConfigBanco(host={self.host!r}, porta={self.porta}, nome={self.nome!r}, usuario={self.usuario!r})"


@dataclass(frozen=True)
class Config:
    banco: ConfigBanco
    contato_email: str
    intervalo_dominio_s: float
    pdf_max_bytes: int
    max_documentos_por_execucao: int
    max_paginas_listagem: int

    @property
    def user_agent(self) -> str:
        # Identificação honesta, com contato, como pede a política de coleta (seção 10 do contexto).
        return f"NqnTechConcursos/0.1 (site publico e gratuito de concursos; contato: {self.contato_email})"


def carregar_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    obrigatorias = ("DB_HOST", "DB_NAME", "COLETOR_DB_USER", "COLETOR_DB_PASSWORD", "COLETOR_CONTATO_EMAIL")
    faltando = [nome for nome in obrigatorias if not env.get(nome)]
    if faltando:
        raise ConfigInvalida(f"variáveis de ambiente ausentes: {', '.join(faltando)}")

    sslmode = env.get("DB_SSLMODE", "require")
    if sslmode not in SSLMODES_VALIDOS:
        raise ConfigInvalida(f"DB_SSLMODE inválido: {sslmode}")
    contato = env["COLETOR_CONTATO_EMAIL"]
    if "@" not in contato:
        raise ConfigInvalida("COLETOR_CONTATO_EMAIL deve ser um e-mail")

    try:
        return Config(
            banco=ConfigBanco(
                host=env["DB_HOST"],
                porta=int(env.get("DB_PORT", "5432")),
                nome=env["DB_NAME"],
                usuario=env["COLETOR_DB_USER"],
                senha=env["COLETOR_DB_PASSWORD"],
                sslmode=sslmode,
            ),
            contato_email=contato,
            intervalo_dominio_s=float(env.get("COLETOR_INTERVALO_S", "2.5")),
            pdf_max_bytes=int(env.get("COLETOR_PDF_MAX_MB", "40")) * 1024 * 1024,
            max_documentos_por_execucao=int(env.get("COLETOR_MAX_DOCUMENTOS", "60")),
            max_paginas_listagem=int(env.get("COLETOR_MAX_PAGINAS", "15")),
        )
    except ValueError as erro:
        raise ConfigInvalida(f"valor numérico inválido: {erro}") from erro
