from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from coletor.ia.provedores import ConfigIA

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
class ConfigBusca:
    """Fluxo único: busca na web (IA) e procura do edital dos pré-cadastros."""

    # Cada alvo de config/busca.yml é pesquisado no máximo uma vez neste intervalo (11 h = 2x/dia com 4 execuções).
    intervalo_h: float = 11.0
    max_alvos: int = 20  # por execução
    max_localizar: int = 30  # pré-cadastros procurados por execução
    intervalo_localizar_h: float = 20.0  # nova tentativa de achar o edital sozinho


@dataclass(frozen=True)
class Config:
    banco: ConfigBanco
    contato_email: str
    intervalo_dominio_s: float
    pdf_max_bytes: int
    max_documentos_por_execucao: int
    max_paginas_listagem: int
    # Páginas do bloco "realizados" da FGV (encerrados). Desligado (0): o site só mostra oportunidades abertas.
    max_paginas_realizados: int = 0
    ia: ConfigIA = field(default_factory=ConfigIA)
    busca: ConfigBusca = field(default_factory=ConfigBusca)

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
            max_paginas_realizados=int(env.get("COLETOR_MAX_PAGINAS_REALIZADOS", "0")),
            ia=ConfigIA(
                gemini_chave=env.get("GEMINI_API_KEY") or None,
                gemini_modelo=env.get("COLETOR_GEMINI_MODELO") or ConfigIA.gemini_modelo,
                gemini_modelos=tuple(
                    m.strip() for m in (env.get("COLETOR_GEMINI_MODELOS") or "").split(",") if m.strip()
                )
                or ((env["COLETOR_GEMINI_MODELO"],) if env.get("COLETOR_GEMINI_MODELO") else ConfigIA.gemini_modelos),
                groq_chave=env.get("GROQ_API_KEY") or None,
                groq_modelo=env.get("COLETOR_GROQ_MODELO") or ConfigIA.groq_modelo,
                openrouter_chave=env.get("OPENROUTER_API_KEY") or None,
                openrouter_modelo=env.get("COLETOR_OPENROUTER_MODELO") or ConfigIA.openrouter_modelo,
                max_chamadas=int(env.get("COLETOR_IA_MAX_CHAMADAS", "30")),
                intervalo_s=float(env.get("COLETOR_IA_INTERVALO_S", "4")),
                max_caracteres=int(env.get("COLETOR_IA_MAX_CARACTERES", "24000")),
            ),
            busca=ConfigBusca(
                intervalo_h=float(env.get("COLETOR_BUSCA_INTERVALO_H", "11")),
                max_alvos=int(env.get("COLETOR_BUSCA_MAX_ALVOS", "20")),
                max_localizar=int(env.get("COLETOR_LOCALIZAR_MAX", "30")),
                intervalo_localizar_h=float(env.get("COLETOR_LOCALIZAR_INTERVALO_H", "20")),
            ),
        )
    except ValueError as erro:
        raise ConfigInvalida(f"valor numérico inválido: {erro}") from erro
