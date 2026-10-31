import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "captura"))

import gerar_municipios_ibge as g

AMOSTRA = [
    {"id": 2507507, "nome": "João Pessoa"},
    {"id": 2515302, "nome": "Sapé"},
    {"id": 2207108, "nome": "Olho D'Água do Piauí"},
    {"id": 5300108, "nome": "Brasília"},
    {"id": 5101837, "nome": "Boa Esperança do Norte", "microrregiao": None},
]


def test_slug_sem_acento_e_sem_pontuacao():
    assert g.slugificar("Olho D'Água do Piauí") == "olho-d-agua-do-piaui"
    assert g.slugificar("  São João del-Rei ") == "sao-joao-del-rei"
    assert g.slugificar("Embu-Guaçu") == "embu-guacu"


def test_uf_vem_do_codigo_mesmo_sem_hierarquia():
    municipios = {m.codigo: m for m in g.converter(AMOSTRA)}
    assert municipios[2515302].uf == "PB"
    assert municipios[5300108].uf == "DF"
    assert municipios[5101837].uf == "MT"
    assert [m.codigo for m in g.converter(AMOSTRA)] == sorted(m["id"] for m in AMOSTRA)


@pytest.mark.parametrize(
    "registro",
    [
        {"id": 9912345, "nome": "X"},
        {"id": 123, "nome": "X"},
        {"id": 2507507, "nome": " "},
    ],
)
def test_registro_invalido(registro):
    with pytest.raises(g.DadosInvalidos):
        g.converter([registro])


def test_slug_repetido_na_mesma_uf_e_erro():
    municipios = g.converter(
        [{"id": 2500001, "nome": "Santa Luzia"}, {"id": 2500002, "nome": "Santa-Luzia"}]
    )
    with pytest.raises(g.DadosInvalidos, match="slugs repetidos"):
        g.validar(municipios, completo=False)


def test_mesmo_nome_em_ufs_diferentes_e_permitido():
    municipios = g.converter(
        [{"id": 2513406, "nome": "Santa Luzia"}, {"id": 3157807, "nome": "Santa Luzia"}]
    )
    g.validar(municipios, completo=False)


def test_lista_incompleta_e_recusada():
    with pytest.raises(g.DadosInvalidos, match="fora da faixa"):
        g.validar(g.converter(AMOSTRA))


def test_sql_escapa_apostrofo():
    sql = g.gerar_sql(g.converter(AMOSTRA), "teste")
    assert "(2207108, 'Olho D''Água do Piauí', 'PI', 'olho-d-agua-do-piaui')" in sql
    assert sql.rstrip().endswith("ON CONFLICT (codigo_ibge) DO NOTHING;")


def test_main_com_entrada_local_incompleta_falha(tmp_path):
    entrada = tmp_path / "m.json"
    entrada.write_text(json.dumps(AMOSTRA), encoding="utf-8")
    saida = tmp_path / "V.sql"
    assert g.main(["--entrada", str(entrada), "--saida", str(saida)]) == 1
    assert not saida.exists()


def test_main_com_lista_completa(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "MINIMO_MUNICIPIOS", 1)
    completos = [
        {"id": codigo * 100_000 + 1, "nome": f"Cidade {uf}"}
        for codigo, uf in g.UF_POR_CODIGO.items()
    ]
    entrada = tmp_path / "m.json"
    entrada.write_text(json.dumps(completos), encoding="utf-8")
    saida = tmp_path / "V.sql"
    assert g.main(["--entrada", str(entrada), "--saida", str(saida)]) == 0
    assert saida.read_text(encoding="utf-8").count("'cidade-") == 27


def test_csv_do_espelho():
    conteudo = "codigo_ibge,nome,latitude,longitude,capital,codigo_uf\n2507507,João Pessoa,-7.1,-34.8,1,25\n"
    assert g.converter(g.ler_csv_espelho(conteudo))[0] == g.Municipio(
        2507507, "João Pessoa", "PB", "joao-pessoa"
    )
