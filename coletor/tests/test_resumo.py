from datetime import date
from decimal import Decimal

import pytest

from coletor.resumo import DadosConcurso, e_oportunidade, gerar_resumo, gerar_slug

HOJE = date(2026, 10, 25)

TJPB = DadosConcurso(
    titulo="Concurso Público para Tribunal de Justiça do Estado da Paraíba",
    situacao="INSCRICOES_ABERTAS",
    banca="FGV",
    orgao="Tribunal de Justiça do Estado da Paraíba",
    abrangencia="ESTADUAL",
    uf="PB",
    ano=2026,
    total_vagas=50,
    salario_min=Decimal("7526.14"),
    salario_max=Decimal("7526.14"),
    escolaridades=("SUPERIOR",),
    areas=("JURIDICA", "TI", "CONTROLE_FISCAL"),
    inscricao_inicio=date(2026, 10, 20),
    inscricao_fim=date(2026, 11, 18),
    data_prova=date(2027, 1, 24),
    taxa_min=Decimal("120.00"),
    taxa_max=Decimal("120.00"),
    isencoes=("CADUNICO", "DOADOR_SANGUE", "DOADOR_MEDULA", "JURADO", "VITIMA_VIOLENCIA_DOMESTICA"),
    isencao_fim=date(2026, 10, 27),
)


def test_resumo_completo():
    assert gerar_resumo(TJPB, HOJE) == (
        "Tribunal de Justiça do Estado da Paraíba (PB) abriu concurso com 50 vagas para nível superior, "
        "salário de R$ 7.526,14, nas áreas controle e fiscal, jurídica e TI. "
        "Inscrições até 18/11/2026, taxa de R$ 120,00. Prova em 24/01/2027. "
        "O edital prevê isenção da taxa para inscritos no CadÚnico, doadores de medula óssea, doadores de sangue "
        "e outros casos. Pedidos de isenção até 27/10/2026. Banca: FGV."
    )


def test_prazo_de_isencao_vencido_some_do_texto():
    texto = gerar_resumo(TJPB, date(2026, 10, 28))
    assert "Pedidos de isenção" not in texto
    assert "O edital prevê isenção da taxa" in texto


def test_incompleto_omite_o_que_falta_sem_inventar():
    dados = DadosConcurso(
        titulo="Concurso Público para a Polícia Militar do Estado do Piauí",
        situacao="EM_ANDAMENTO",
        banca="FGV",
        orgao="Polícia Militar do Estado do Piauí",
        abrangencia="ESTADUAL",
        uf="PI",
        tem_avisos=True,
    )
    assert gerar_resumo(dados, HOJE) == (
        "Polícia Militar do Estado do Piauí (PI) tem concurso. Banca: FGV. "
        "Alguns dados não foram identificados automaticamente: confira o edital."
    )


def test_previsto_sem_edital():
    dados = DadosConcurso(
        titulo="Concurso previsto",
        situacao="PREVISTO",
        orgao="Câmara Municipal de Taubaté",
        abrangencia="MUNICIPAL",
        uf="SP",
        municipio="Taubaté",
    )
    assert gerar_resumo(dados, HOJE) == (
        "Câmara Municipal de Taubaté (SP) tem concurso previsto. Ainda não há edital publicado."
    )


def test_municipio_aparece_quando_nao_esta_no_nome():
    dados = DadosConcurso(
        titulo="x", situacao="INSCRICOES_ABERTAS", orgao="Secretaria de Educação", abrangencia="MUNICIPAL", uf="BA",
        municipio="Salvador", total_vagas=1, inscricao_fim=date(2026, 11, 1),
    )  # fmt: skip
    assert gerar_resumo(dados, HOJE).startswith("Secretaria de Educação (Salvador/BA) abriu concurso com 1 vaga.")


def test_inscricoes_por_abrir_e_faixas_de_valores():
    dados = DadosConcurso(
        titulo="x",
        situacao="INSCRICOES_ABERTAS",
        orgao="Dataprev",
        abrangencia="NACIONAL",
        total_vagas=1200,
        salario_min=Decimal("3500"),
        salario_max=Decimal("12800.5"),
        escolaridades=("SUPERIOR", "MEDIO"),
        areas=("TI", "ADMINISTRATIVA", "JURIDICA", "COMUNICACAO_ARTES", "CONTROLE_FISCAL", "OUTRAS"),
        inscricao_inicio=date(2026, 11, 3),
        inscricao_fim=date(2026, 12, 1),
        taxa_min=Decimal("70"),
        taxa_max=Decimal("90"),
    )
    texto = gerar_resumo(dados, HOJE)
    assert texto.startswith(
        "Dataprev publicou edital de concurso com 1.200 vagas para níveis médio e superior, "
        "salários de R$ 3.500,00 a R$ 12.800,50, em 5 áreas, como administrativa, controle e fiscal e jurídica."
    )
    assert "Inscrições de 03/11/2026 a 01/12/2026, taxas de R$ 70,00 a R$ 90,00." in texto


def test_so_isencao_outra():
    dados = DadosConcurso(titulo="x", situacao="INSCRICOES_ABERTAS", orgao="Órgão", isencoes=("OUTRA",))
    assert "O edital prevê isenção da taxa para alguns casos." in gerar_resumo(dados, HOJE)


def test_linguagem_informativa():
    assert "direito" not in gerar_resumo(TJPB, HOJE).lower()


def test_slug_estavel_e_unico():
    ocupados: set[str] = set()
    primeiro = gerar_slug(TJPB, ocupados, 2026)
    assert primeiro == "tribunal-de-justica-do-estado-da-paraiba-2026"
    ocupados.add(primeiro)
    assert gerar_slug(TJPB, ocupados, 2026) == "tribunal-de-justica-do-estado-da-paraiba-2026-2"


def test_slug_curto_sem_ano_e_cnu():
    longo = DadosConcurso(titulo="x", situacao="PREVISTO", orgao="Secretaria " + "de Estado " * 20 + "da Fazenda")
    slug = gerar_slug(longo, set(), 2027)
    assert len(slug) <= 80 and slug.endswith("-2027") and "--" not in slug
    cnu = DadosConcurso(titulo="CPNU 2", situacao="INSCRICOES_ABERTAS", unificado=True, ano=2026)
    assert gerar_slug(cnu, set(), 2026) == "concurso-nacional-unificado-2026"


@pytest.mark.parametrize(
    ("situacao", "isencao_fim", "esperado"),
    [
        ("PREVISTO", None, True),
        ("INSCRICOES_ABERTAS", None, True),
        ("EM_ANDAMENTO", None, False),
        ("EM_ANDAMENTO", date(2026, 10, 25), True),  # prazo de isenção termina hoje
        ("EM_ANDAMENTO", date(2026, 10, 24), False),
        ("ENCERRADO", date(2026, 12, 1), False),
    ],
)
def test_oportunidade(situacao, isencao_fim, esperado):
    assert e_oportunidade(situacao, isencao_fim, HOJE) is esperado
