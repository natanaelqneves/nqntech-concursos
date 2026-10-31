import json

import pytest

from verificar_ambiente import hosts_expostos, ler_env_texto, parse_compose_ps


def _servico(nome, estado, saude="", exit_code=0, hosts=()):
    return {
        "Service": nome,
        "State": estado,
        "Health": saude,
        "ExitCode": exit_code,
        "Publishers": [
            {"URL": h, "TargetPort": 1, "PublishedPort": 1, "Protocol": "tcp"}
            for h in hosts
        ],
    }


ITENS = [
    _servico("postgres", "running", "healthy", hosts=["127.0.0.1"]),
    _servico("flyway", "exited", exit_code=0),
    _servico("mailpit", "running", hosts=["127.0.0.1", "127.0.0.1"]),
]


@pytest.mark.parametrize(
    "saida",
    [json.dumps(ITENS), "\n".join(json.dumps(i) for i in ITENS)],
    ids=["array", "uma-linha-por-servico"],
)
def test_entende_os_dois_formatos_do_compose_ps(saida):
    servicos = parse_compose_ps(saida)

    assert set(servicos) == {"postgres", "flyway", "mailpit"}
    assert servicos["postgres"].saude == "healthy"
    assert servicos["flyway"].estado == "exited"
    assert servicos["flyway"].codigo_saida == 0


def test_saida_vazia_nao_quebra():
    assert parse_compose_ps("  \n") == {}


def test_porta_em_todas_as_interfaces_e_detectada():
    servicos = parse_compose_ps(
        json.dumps([*ITENS[:2], _servico("mailpit", "running", hosts=["0.0.0.0"])])
    )

    assert hosts_expostos(servicos) == ["mailpit -> 0.0.0.0"]


def test_portas_em_loopback_nao_sao_expostas():
    assert hosts_expostos(parse_compose_ps(json.dumps(ITENS))) == []


def test_porta_nao_publicada_e_ignorada():
    item = _servico("postgres", "running", "healthy")
    item["Publishers"] = [
        {"URL": "", "TargetPort": 5432, "PublishedPort": 0, "Protocol": "tcp"}
    ]

    assert hosts_expostos(parse_compose_ps(json.dumps([item]))) == []


def test_ler_env_ignora_comentarios_e_remove_aspas():
    env = ler_env_texto('# comentario\n\nA=1\nB="com espaco"\n# C=nao\nD=x=y\n')

    assert env == {"A": "1", "B": "com espaco", "D": "x=y"}
