import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))

import neon_url  # noqa: E402

URL = "postgresql://neondb_owner:npg_a%2Fb@ep-cool-1234.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"


def test_interpreta_string_do_painel():
    c = neon_url.interpretar(URL)
    assert (c.host, c.porta, c.banco, c.usuario, c.senha) == (
        "ep-cool-1234.sa-east-1.aws.neon.tech",
        5432,
        "neondb",
        "neondb_owner",
        "npg_a/b",
    )
    assert (
        c.jdbc
        == "jdbc:postgresql://ep-cool-1234.sa-east-1.aws.neon.tech:5432/neondb?sslmode=require"
    )


def test_aceita_comando_psql_copiado():
    assert neon_url.interpretar(f"psql '{URL}'").banco == "neondb"


@pytest.mark.parametrize(
    "ruim", ["mysql://a:b@h/db", "postgresql://h/db", "postgresql://a:b@h", ""]
)
def test_rejeita_string_incompleta(ruim):
    with pytest.raises(neon_url.UrlInvalida):
        neon_url.interpretar(ruim)


def test_modo_admin_mascara_senha_e_grava_env(tmp_path, monkeypatch, capsys):
    env = tmp_path / "env"
    monkeypatch.setenv("NEON_ADMIN_URL", URL)
    monkeypatch.setenv("GITHUB_ENV", str(env))

    assert neon_url.main(["--admin"]) == 0

    assert "::add-mask::npg_a/b" in capsys.readouterr().out
    conteudo = env.read_text()
    assert (
        "FLYWAY_USER=neondb_owner\n" in conteudo and "PGSSLMODE=require\n" in conteudo
    )


def test_modo_host_nunca_expoe_a_senha(tmp_path, monkeypatch, capsys):
    saida = tmp_path / "out"
    monkeypatch.setenv("NEON_ADMIN_URL", URL)
    monkeypatch.setenv("GITHUB_OUTPUT", str(saida))

    assert neon_url.main(["--host"]) == 0

    assert (
        saida.read_text()
        == "db_host=ep-cool-1234.sa-east-1.aws.neon.tech\ndb_name=neondb\n"
    )
    assert "npg_a" not in capsys.readouterr().out + saida.read_text()


def test_secret_ausente(monkeypatch, capsys):
    monkeypatch.delenv("NEON_ADMIN_URL", raising=False)
    assert neon_url.main(["--host"]) == 1
    assert "NEON_ADMIN_URL" in capsys.readouterr().out
