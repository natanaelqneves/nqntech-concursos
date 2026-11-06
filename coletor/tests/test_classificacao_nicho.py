import pytest

from coletor.classificacao.nicho import ClassificadorNicho
from coletor.classificacao.regras import RegrasInvalidas


@pytest.fixture(scope="module")
def nicho() -> ClassificadorNicho:
    return ClassificadorNicho.padrao()


@pytest.mark.parametrize(
    ("texto", "esperada"),
    [
        # controle externo e interno
        ("Tribunal de Contas do Estado da Paraíba", "tribunal_contas"),
        ("TCE-SP 2026", "tribunal_contas"),
        ("Tribunal de Contas da União - Auditor Federal de Controle Externo", "tribunal_contas"),
        ("Ministério Público de Contas do Estado do Pará", "tribunal_contas"),
        ("TCM-RJ", "tribunal_contas"),
        ("Controladoria-Geral da União", "controladoria"),
        ("CGE-MG Auditor Interno", "controladoria"),
        # justiça
        ("Tribunal de Justiça da Paraíba", "tribunal"),
        ("TJPB 2026", "tribunal"),
        ("Tribunal Regional do Trabalho da 13ª Região", "tribunal"),
        ("TRT 4", "tribunal"),
        ("Tribunal Regional Eleitoral de São Paulo", "tribunal"),
        ("Superior Tribunal de Justiça", "tribunal"),
        ("Tribunal de Justiça Militar de Minas Gerais", "tribunal"),
        ("Juiz Substituto - Tribunal de Justiça do Paraná", "tribunal"),
        ("Ministério Público do Estado da Bahia", "ministerio_publico"),
        ("MPU 2026", "ministerio_publico"),
        ("Defensoria Pública da União", "defensoria"),
        ("DPE-RS Defensor Público", "defensoria"),
        ("Advocacia-Geral da União", "advocacia_publica"),
        ("Procuradoria-Geral do Estado de Pernambuco", "advocacia_publica"),
        ("Prefeitura de Sapé - Procurador Municipal", "advocacia_publica"),
        # fisco
        ("Receita Federal do Brasil - Auditor-Fiscal", "fisco"),
        ("SEFAZ-AL Auditor Fiscal da Receita Estadual", "fisco"),
        ("Secretaria de Estado da Fazenda de Minas Gerais", "fisco"),
        ("Secretaria da Economia do Distrito Federal", "fisco"),
        ("Prefeitura de São Paulo - Auditor Fiscal Tributário Municipal", "fisco"),
        # legislativo, conselhos, regulação
        ("Câmara dos Deputados", "legislativo"),
        ("Assembleia Legislativa da Paraíba", "legislativo"),
        ("ALERJ", "legislativo"),
        ("Câmara Municipal de João Pessoa", "legislativo"),
        ("Conselho Regional de Medicina do Paraná", "conselho"),
        ("CREA-SP", "conselho"),
        ("Coren-PB", "conselho"),
        ("Conselho Federal de Contabilidade", "conselho"),
        ("Banco Central do Brasil", "regulacao"),
        ("Agência Nacional de Energia Elétrica", "regulacao"),
        ("ANVISA", "regulacao"),
        # segurança e militares
        ("Polícia Federal - Agente", "policial"),
        ("Polícia Rodoviária Federal", "policial"),
        ("Polícia Militar da Paraíba - Soldado", "policial"),
        ("Corpo de Bombeiros Militar do Distrito Federal", "policial"),
        ("PC-SP Escrivão", "policial"),
        ("Guarda Civil Municipal de Campinas", "policial"),
        ("Polícia Científica de Pernambuco - Perito Criminal", "policial"),
        ("DETRAN-PB", "policial"),
        ("Exército Brasileiro - EsPCEx", "militar"),
        ("Escola de Sargentos das Armas", "militar"),
        ("Marinha do Brasil - Colégio Naval", "militar"),
        ("Comando da Aeronáutica - EEAR", "militar"),
    ],
)
def test_categoria_do_nicho(nicho, texto, esperada):
    assert nicho.categoria(texto) == esperada


@pytest.mark.parametrize(
    "texto",
    [
        "Prefeitura Municipal de Sapé - Professor",
        "Câmara Municipal de Vitória da Conquista",  # não é a capital Vitória
        "Câmara Municipal de Itabaiana",
        "Universidade Federal da Paraíba - Técnico em Laboratório",
        "Hospital Municipal - Enfermeiro",
        "Ana Maria - processo seletivo de estágio",  # "ana" sozinho não é agência
        "Essa prefeitura abriu concurso",  # "essa" não é a Escola de Sargentos
        "",
    ],
)
def test_fora_do_nicho(nicho, texto):
    assert nicho.categoria(texto) is None


def test_cnu_e_sempre_unificado(nicho):
    assert nicho.categoria("Concurso Nacional Unificado", unificado=True) == "unificado"
    assert nicho.categoria(None, None, unificado=True) == "unificado"


def test_orgao_e_titulo_juntos(nicho):
    assert nicho.categoria("Governo do Estado da Paraíba", "Concurso Polícia Penal") == "policial"
    assert nicho.categoria(None, "Tribunal de Justiça do Ceará") == "tribunal"


def test_modo_padrao_exclusivo(nicho):
    assert nicho.exclusivo


def test_config_invalida():
    with pytest.raises(RegrasInvalidas):
        ClassificadorNicho.de_dados({"modo": "outro", "categorias": {"x": ["a"]}})
    with pytest.raises(RegrasInvalidas):
        ClassificadorNicho.de_dados({"modo": "destaque", "categorias": {}})
    with pytest.raises(RegrasInvalidas):
        ClassificadorNicho.de_dados({"modo": "destaque", "categorias": {"x": ["("]}})
    assert not ClassificadorNicho.de_dados({"modo": "destaque", "categorias": {"x": ["a"]}}).exclusivo
