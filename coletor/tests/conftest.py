from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def ler_fixture(caminho: str) -> str:
    return (FIXTURES / caminho).read_text(encoding="utf-8")


def bytes_fixture(caminho: str) -> bytes:
    return (FIXTURES / caminho).read_bytes()


@pytest.fixture
def fixture_texto():
    return ler_fixture


@pytest.fixture
def fixture_bytes():
    return bytes_fixture


def _parametros_teste(prefixo: str) -> dict[str, str] | None:
    """Banco de teste já migrado (CI: Postgres de serviço + Flyway; local: qualquer Postgres migrado)."""
    host = os.environ.get("TESTE_DB_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": os.environ.get("TESTE_DB_PORT", "5432"),
        "dbname": os.environ["TESTE_DB_NAME"],
        "user": os.environ[f"TESTE_{prefixo}_USER"],
        "password": os.environ[f"TESTE_{prefixo}_PASSWORD"],
    }


@pytest.fixture
def parametros_coletor() -> dict[str, str]:
    parametros = _parametros_teste("COLETOR")
    if parametros is None:
        pytest.skip("defina TESTE_DB_* para rodar os testes de integração com o banco")
    return parametros


@pytest.fixture
def conn_admin():
    parametros = _parametros_teste("ADMIN")
    if parametros is None:
        pytest.skip("defina TESTE_DB_* para rodar os testes de integração com o banco")
    import psycopg

    with psycopg.connect(**parametros, autocommit=True) as conn:
        yield conn
