"""Converte a string de conexão do Neon (secret NEON_ADMIN_URL) nas variáveis usadas pelos workflows.

    postgresql://usuario:senha@ep-xxx.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require

--admin  grava no $GITHUB_ENV: FLYWAY_URL/USER/PASSWORD e PGHOST/PGUSER/PGPASSWORD/PGDATABASE (senha mascarada)
--host   grava no $GITHUB_OUTPUT só db_host e db_name (não são segredo; a senha nunca sai deste passo)
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit


class UrlInvalida(ValueError):
    pass


@dataclass(frozen=True)
class ConexaoNeon:
    host: str
    porta: int
    banco: str
    usuario: str
    senha: str

    @property
    def jdbc(self) -> str:
        return (
            f"jdbc:postgresql://{self.host}:{self.porta}/{self.banco}?sslmode=require"
        )


def interpretar(url: str) -> ConexaoNeon:
    url = url.strip().strip("'\"")
    if url.startswith("psql "):
        url = (
            url[5:].strip().strip("'\"")
        )  # aceita o comando "psql '...'" copiado do painel do Neon
    partes = urlsplit(url)
    if partes.scheme not in ("postgresql", "postgres"):
        raise UrlInvalida("a string deve começar com postgresql://")
    if not partes.hostname or not partes.username or not partes.password:
        raise UrlInvalida("faltam host, usuário ou senha na string de conexão")
    banco = partes.path.lstrip("/")
    if not banco:
        raise UrlInvalida("falta o nome do banco (ex.: /neondb) na string de conexão")
    return ConexaoNeon(
        partes.hostname,
        partes.port or 5432,
        unquote(banco),
        unquote(partes.username),
        unquote(partes.password),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--admin", action="store_true")
    modo.add_argument("--host", action="store_true")
    args = parser.parse_args(argv)

    bruta = os.environ.get("NEON_ADMIN_URL", "")
    if not bruta:
        print(
            "::error title=Secret ausente::Cadastre o secret NEON_ADMIN_URL (veja docs/PENDENCIAS.md)"
        )
        return 1
    try:
        conexao = interpretar(bruta)
    except UrlInvalida as erro:
        print(f"::error title=NEON_ADMIN_URL inválida::{erro}")
        return 1

    if args.host:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as saida:
            saida.write(f"db_host={conexao.host}\ndb_name={conexao.banco}\n")
        return 0

    print(f"::add-mask::{conexao.senha}")
    variaveis = {
        "FLYWAY_URL": conexao.jdbc,
        "FLYWAY_USER": conexao.usuario,
        "FLYWAY_PASSWORD": conexao.senha,
        "PGHOST": conexao.host,
        "PGPORT": str(conexao.porta),
        "PGDATABASE": conexao.banco,
        "PGUSER": conexao.usuario,
        "PGPASSWORD": conexao.senha,
        "PGSSLMODE": "require",
    }
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as env:
        env.writelines(f"{chave}={valor}\n" for chave, valor in variaveis.items())
    print(f"banco: {conexao.banco} em {conexao.host} (usuário {conexao.usuario})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
