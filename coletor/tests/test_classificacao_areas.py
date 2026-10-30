import pytest

from coletor.classificacao.areas import AREA_PADRAO, ClassificadorArea
from coletor.classificacao.regras import RegrasInvalidas
from coletor.extratores.fgv import ExtratorFGV

CODIGOS_CATALOGO = frozenset(
    {
        "ADMINISTRATIVA", "BANCARIA", "CONTROLE_FISCAL", "EDUCACAO", "ENGENHARIA_ARQUITETURA", "JURIDICA",
        "LEGISLATIVA", "MEIO_AMBIENTE_AGRARIA", "POLICIAL_SEGURANCA", "SAUDE", "TI", "ASSISTENCIA_SOCIAL",
        "COMUNICACAO_ARTES", "OPERACIONAL", "OUTRAS",
    }
)  # fmt: skip


@pytest.fixture(scope="module")
def classificador() -> ClassificadorArea:
    return ClassificadorArea.padrao()


def test_areas_yml_usa_so_codigos_do_catalogo(classificador):
    assert classificador.codigos <= CODIGOS_CATALOGO
    assert classificador.codigos == CODIGOS_CATALOGO  # toda área do catálogo tem regra (menos OUTRAS, o padrão)


@pytest.mark.parametrize(
    ("nome", "especialidade", "area"),
    [
        # uma ou mais por área
        ("Analista de Sistemas", None, "TI"),
        ("Técnico em Informática", None, "TI"),
        ("Analista Judiciário", "TI – Banco de Dados", "TI"),
        ("Médico", "Cardiologia", "SAUDE"),
        ("Técnico em Enfermagem", None, "SAUDE"),
        ("Agente Comunitário de Saúde", None, "SAUDE"),
        ("Professor de Educação Básica", "Matemática", "EDUCACAO"),
        ("Pedagogo", None, "EDUCACAO"),
        ("Analista Judiciário", "Área Judiciária", "JURIDICA"),
        ("Juiz Substituto", None, "JURIDICA"),
        ("Oficial de Justiça Avaliador", None, "JURIDICA"),
        ("Auditor Fiscal da Receita Estadual", None, "CONTROLE_FISCAL"),
        ("Analista Judiciário", "Contabilidade", "CONTROLE_FISCAL"),
        ("Escriturário", None, "BANCARIA"),
        ("Engenheiro", "Civil", "ENGENHARIA_ARQUITETURA"),
        ("Arquiteto e Urbanista", None, "ENGENHARIA_ARQUITETURA"),
        ("Engenheiro Agrônomo", None, "MEIO_AMBIENTE_AGRARIA"),
        ("Médico Veterinário", None, "MEIO_AMBIENTE_AGRARIA"),
        ("Soldado", None, "POLICIAL_SEGURANCA"),
        ("Delegado de Polícia", None, "POLICIAL_SEGURANCA"),
        ("Guarda Municipal", None, "POLICIAL_SEGURANCA"),
        ("Agente de Trânsito", None, "POLICIAL_SEGURANCA"),
        ("Analista Legislativo", None, "LEGISLATIVA"),
        ("Assistente Social", None, "ASSISTENCIA_SOCIAL"),
        ("Jornalista", None, "COMUNICACAO_ARTES"),
        ("Bibliotecário", None, "COMUNICACAO_ARTES"),
        ("Motorista", None, "OPERACIONAL"),
        ("Auxiliar de Serviços Gerais", None, "OPERACIONAL"),
        ("Assistente Administrativo", None, "ADMINISTRATIVA"),
        ("Técnico Judiciário", "Área Administrativa", "ADMINISTRATIVA"),
    ],
)
def test_classifica_por_area(classificador, nome, especialidade, area):
    assert classificador.classificar(nome, especialidade).codigo == area


@pytest.mark.parametrize(
    ("nome", "especialidade", "area", "motivo"),
    [
        # Profissão no nome define a área, mesmo com especialidade de outra área.
        ("Professor", "Informática", "EDUCACAO", "principal:professor"),
        ("Auditor Fiscal", "Tecnologia da Informação", "CONTROLE_FISCAL", "principal:auditor fiscal"),
        # Sem profissão "forte" no nome, a especialidade decide.
        ("Analista Legislativo", "Tecnologia da Informação", "TI", "especialidade:tecnologia da informacao"),
        ("Analista em Gestão", "Engenharia de Software", "TI", "especialidade:engenharia de software"),
        ("Oficial do Quadro de Saúde", "Médico", "SAUDE", "especialidade:medico"),
        # O termo mais longo vence: "engenheiro agrônomo" é mais específico que "engenheiro".
        ("Engenheiro Agrônomo", None, "MEIO_AMBIENTE_AGRARIA", "principal:engenheiro agronomo"),
        ("Técnico em Segurança do Trabalho", None, "ENGENHARIA_ARQUITETURA", None),
        ("Médico Legista", None, "POLICIAL_SEGURANCA", "principal:medico legista"),
    ],
)
def test_casos_ambiguos(classificador, nome, especialidade, area, motivo):
    resultado = classificador.classificar(nome, especialidade)
    assert resultado.codigo == area
    if motivo:
        assert resultado.motivo == motivo


@pytest.mark.parametrize(
    ("nome", "especialidade", "nao_pode_ser"),
    [
        ("Técnico em Radiologia", None, "TI"),  # "tecnologia em radiologia" exclui TI
        ("Oficial de Justiça", None, "POLICIAL_SEGURANCA"),  # "oficial" é policial, mas não este
        ("Assistente Social", None, "ADMINISTRATIVA"),
        ("Analista", "Segurança da Informação", "POLICIAL_SEGURANCA"),
        ("Engenheiro", "Engenharia de Software", "ENGENHARIA_ARQUITETURA"),
        ("Fiscal de Obras", None, "CONTROLE_FISCAL"),
    ],
)
def test_termos_de_exclusao(classificador, nome, especialidade, nao_pode_ser):
    assert classificador.classificar(nome, especialidade).codigo != nao_pode_ser


def test_palavra_inteira_e_sem_acento(classificador):
    assert classificador.classificar("ANALISTA - ÁREA DE TI").codigo == "TI"
    assert classificador.classificar("Agente Ativo").codigo != "TI"  # "ti" dentro de "ativo" não conta


def test_orgao_e_o_ultimo_recurso(classificador):
    resultado = classificador.classificar("Cargo 101", None, orgao="Banco do Nordeste do Brasil")
    assert (resultado.codigo, resultado.motivo) == ("BANCARIA", "orgao:banco do nordeste")
    # Com área identificada pelo cargo, o órgão não muda nada.
    assert classificador.classificar("Analista de Sistemas", None, orgao="Banco do Brasil").codigo == "TI"


def test_sem_regra_vai_para_outras(classificador):
    resultado = classificador.classificar("Cargo 101", "Perfil 7")
    assert resultado.codigo == AREA_PADRAO
    assert not resultado.identificada


def test_cargos_reais_do_edital_tjpb(classificador, fixture_texto):
    edital = ExtratorFGV().extrair(fixture_texto("fgv/edital_tjpb26_1.txt"))
    areas = {c.especialidade: classificador.classificar(c.nome, c.especialidade).codigo for c in edital.cargos}

    assert all(area != AREA_PADRAO for area in areas.values()), areas
    assert areas["TI – Desenvolvimento de Sistemas"] == "TI"
    assert areas["TI – Banco de Dados"] == "TI"
    assert sum(1 for a in areas.values() if a == "TI") >= 3


def test_area_fora_do_catalogo_e_erro_de_configuracao():
    with pytest.raises(RegrasInvalidas, match="NAO_EXISTE"):
        ClassificadorArea.de_dados({"areas": {"NAO_EXISTE": {"termos": ["x"]}}}, areas_validas=CODIGOS_CATALOGO)
    with pytest.raises(RegrasInvalidas, match="OUTRAS"):
        ClassificadorArea.de_dados({"areas": {"OUTRAS": {"termos": ["x"]}}})
    with pytest.raises(RegrasInvalidas, match="areas"):
        ClassificadorArea.de_dados({})


@pytest.mark.parametrize(
    ("nome", "area"),
    [
        # Abreviações dos quadros do IBAM/IBADE (ensaio de 29/10/2026).
        ("Prof. de Lingua Portuguesa", "EDUCACAO"),
        ("Aux. Educacional - Lau Mello", "EDUCACAO"),
        ("Acs Usf Boa Vista", "SAUDE"),
        ("Med. Anestesista", "SAUDE"),
        ("Tec. em Enfermagem", "SAUDE"),
        ("Apoio Ao Estu. com Deficiencia", "EDUCACAO"),
    ],
)
def test_abreviacoes_sao_expandidas(classificador, nome, area):
    assert classificador.classificar(nome).codigo == area
