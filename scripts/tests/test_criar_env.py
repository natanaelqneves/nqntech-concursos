from pathlib import Path

import criar_env
import verificar_ambiente

EXEMPLO = (Path(__file__).resolve().parents[2] / ".env.example").read_text(
    encoding="utf-8"
)


def test_troca_todas_as_senhas_de_exemplo_das_linhas_ativas():
    env = verificar_ambiente.ler_env_texto(criar_env.gerar_conteudo(EXEMPLO, None))

    assert not [k for k, v in env.items() if v.startswith("troque-")]
    assert len(env["POSTGRES_PASSWORD"]) >= 24
    assert (
        env["POSTGRES_PASSWORD"]
        != env["COLETOR_DB_PASSWORD"]
        != env["SITE_DB_PASSWORD"]
    )


def test_nao_ativa_nem_altera_o_bloco_de_producao():
    conteudo = criar_env.gerar_conteudo(EXEMPLO, "eu@exemplo.com")
    env = verificar_ambiente.ler_env_texto(conteudo)

    assert env["DB_SSLMODE"] == "disable"
    assert env["DB_HOST"] == "127.0.0.1"
    assert "FLYWAY_PASSWORD" not in env
    assert "NEON_ADMIN_URL" not in env
    assert "# NEON_ADMIN_URL=postgresql://neondb_owner:SENHA@" in conteudo


def test_aplica_email_informado():
    env = verificar_ambiente.ler_env_texto(
        criar_env.gerar_conteudo(EXEMPLO, "eu@exemplo.com")
    )

    assert env["COLETOR_CONTATO_EMAIL"] == "eu@exemplo.com"


def test_nao_sobrescreve_env_existente(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("POSTGRES_PASSWORD=minha\n", encoding="utf-8")
    monkeypatch.setattr(criar_env, "RAIZ", tmp_path)

    assert criar_env.main([]) == 0
    assert (tmp_path / ".env").read_text(
        encoding="utf-8"
    ) == "POSTGRES_PASSWORD=minha\n"


def test_rejeita_email_invalido(tmp_path, monkeypatch):
    monkeypatch.setattr(criar_env, "RAIZ", tmp_path)

    assert criar_env.main(["--email", "nao-e-email"]) == 2
    assert not (tmp_path / ".env").exists()
