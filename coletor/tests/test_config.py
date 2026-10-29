import pytest

from coletor.config import ConfigInvalida, carregar_config

BASE = {
    "DB_HOST": "ep-x.neon.tech",
    "DB_NAME": "neondb",
    "COLETOR_DB_USER": "coletor_app",
    "COLETOR_DB_PASSWORD": "segredo-muito-secreto",
    "COLETOR_CONTATO_EMAIL": "eu@exemplo.com",
}


def test_padroes_seguros():
    config = carregar_config(BASE)
    assert config.banco.sslmode == "require"
    assert config.banco.parametros()["application_name"] == "nqntech-coletor"
    assert "eu@exemplo.com" in config.user_agent


def test_senha_nunca_aparece_no_repr():
    assert "segredo-muito-secreto" not in repr(carregar_config(BASE))


@pytest.mark.parametrize(
    "alteracao",
    [
        {"DB_HOST": ""},
        {"COLETOR_DB_PASSWORD": ""},
        {"DB_SSLMODE": "talvez"},
        {"COLETOR_CONTATO_EMAIL": "sem-arroba"},
        {"COLETOR_MAX_DOCUMENTOS": "muitos"},
    ],
)
def test_configuracao_invalida(alteracao):
    with pytest.raises(ConfigInvalida):
        carregar_config({**BASE, **alteracao})
