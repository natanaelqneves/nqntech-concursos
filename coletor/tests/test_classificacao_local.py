import pytest

from coletor.classificacao.destaques import DetectorCNU
from coletor.classificacao.escolaridade import InferidorEscolaridade
from coletor.classificacao.local import IndiceMunicipios, Local, Municipio, ResolvedorLocal, ufs_citadas
from coletor.classificacao.orgao import OrgaoInferido, inferir_orgao

# Recorte real da tabela do IBGE (V6): homônimos de propósito.
MUNICIPIOS = [
    Municipio(3302403, "Macaé", "RJ", "macae"),
    Municipio(2927408, "Salvador", "BA", "salvador"),
    Municipio(2513851, "Santo André", "PB", "santo-andre"),
    Municipio(3547809, "Santo André", "SP", "santo-andre"),
    Municipio(1501402, "Belém", "PA", "belem"),
    Municipio(2501906, "Belém", "PB", "belem"),
    Municipio(2700805, "Belém", "AL", "belem"),
    Municipio(2903904, "Bom Jesus da Lapa", "BA", "bom-jesus-da-lapa"),
    Municipio(4202537, "Bom Jesus", "SC", "bom-jesus"),
    Municipio(4302303, "Bom Jesus", "RS", "bom-jesus"),
    Municipio(4205506, "Fraiburgo", "SC", "fraiburgo"),
    Municipio(3304557, "Rio de Janeiro", "RJ", "rio-de-janeiro"),
]


@pytest.fixture(scope="module")
def resolvedor() -> ResolvedorLocal:
    return ResolvedorLocal(IndiceMunicipios(MUNICIPIOS))


@pytest.mark.parametrize(
    ("titulo", "nome", "esfera", "uf", "municipio"),
    [
        (
            "Concurso Público para Tribunal de Justiça do Estado da Paraíba",
            "Tribunal de Justiça do Estado da Paraíba",
            "ESTADUAL",
            "PB",
            None,
        ),
        ("Concurso Público para a Prefeitura de Macaé", "Prefeitura de Macaé", "MUNICIPAL", None, "Macaé"),
        (
            "Concurso Público para a Empresa de Tecnologia e Informações da Previdência - Dataprev",
            "Empresa de Tecnologia e Informações da Previdência",
            "FEDERAL",
            None,
            None,
        ),
        (
            "Concurso Público para a Polícia Civil do Estado do Paraná",
            "Polícia Civil do Estado do Paraná",
            "ESTADUAL",
            "PR",
            None,
        ),
        (
            "Concurso Público para a Prefeitura Municipal do Salvador 2026 - Guarda",
            "Prefeitura Municipal do Salvador",
            "MUNICIPAL",
            None,
            "Salvador",
        ),
        # Nomes com hífen não são cortados (antes viravam só "Controladoria").
        (
            "Concurso Público para a Controladoria-Geral do Estado de Santa Catarina",
            "Controladoria-Geral do Estado de Santa Catarina",
            "ESTADUAL",
            "SC",
            None,
        ),
        # A região faz parte do nome (antes os TRTs viravam o mesmo órgão).
        (
            "Concurso Público para o Tribunal Regional do Trabalho - 13ª Região",
            "Tribunal Regional do Trabalho da 13ª Região",
            "FEDERAL",
            None,
            None,
        ),
        # Antes saía só "5ª Região".
        (
            "XVI Concurso Público para provimento de cargos de Juiz Federal Substituto da 5ª Região",
            "Tribunal Regional Federal da 5ª Região",
            "FEDERAL",
            None,
            None,
        ),
        # Texto antes do órgão.
        (
            "XXXIX Concurso para Ingresso na Classe Inicial da Carreira do Ministério Público do Estado do Rio de "
            "Janeiro",
            "Ministério Público do Estado do Rio de Janeiro",
            "ESTADUAL",
            "RJ",
            None,
        ),
        # UF na sigla do fim do título.
        (
            "Concurso Público para a Secretaria de Estado da Administração - SEAD-AP - Peritos",
            "Secretaria de Estado da Administração",
            "ESTADUAL",
            "AP",
            None,
        ),
        ("Camara de Fraiburgo/SC", "Camara de Fraiburgo/SC", "MUNICIPAL", "SC", "Fraiburgo"),
        (
            "Concurso Público para a Procuradoria Geral do Município de Niterói",
            "Procuradoria Geral do Município de Niterói",
            "MUNICIPAL",
            None,
            "Niterói",
        ),
        ("Concurso Público para o Governo do Distrito Federal", "Governo do Distrito Federal", "ESTADUAL", "DF", None),
        (
            "Concurso Público para a Universidade Federal da Paraíba",
            "Universidade Federal da Paraíba",
            "FEDERAL",
            "PB",
            None,
        ),
        ("Concurso Público para a Câmara dos Deputados", "Câmara dos Deputados", "FEDERAL", None, None),
    ],
)
def test_orgao_inferido_do_titulo(titulo, nome, esfera, uf, municipio):
    orgao = inferir_orgao(titulo)
    assert orgao is not None
    assert (orgao.nome, orgao.esfera, orgao.uf, orgao.municipio) == (nome, esfera, uf, municipio)


def test_titulo_sem_orgao():
    assert inferir_orgao("Concurso Público Nacional Unificado 2") is None


@pytest.mark.parametrize(
    ("orgao", "contexto", "esperado"),
    [
        (OrgaoInferido("Prefeitura de Macaé", "MUNICIPAL", None, "Macaé"), "", Local("MUNICIPAL", "RJ", 3302403)),
        (OrgaoInferido("Câmara de Fraiburgo", "MUNICIPAL", "SC", "Fraiburgo"), "", Local("MUNICIPAL", "SC", 4205506)),
        # Homônimo resolvido pela UF citada na página/edital.
        (
            OrgaoInferido("Prefeitura de Santo André", "MUNICIPAL", None, "Santo André"),
            "Prefeitura Municipal de Santo André - Estado de São Paulo",
            Local("MUNICIPAL", "SP", 3547809),
        ),
        (
            OrgaoInferido("Prefeitura de Santo André", "MUNICIPAL", None, "Santo André"),
            "Edital 01/2026 Santo André/PB",
            Local("MUNICIPAL", "PB", 2513851),
        ),
        (OrgaoInferido("Tribunal de Justiça da Paraíba", "ESTADUAL", "PB", None), "", Local("ESTADUAL", "PB")),
        (
            OrgaoInferido("Secretaria de Estado de Justiça e Segurança Pública", "ESTADUAL", None, None),
            "Governo do Estado de Mato Grosso do Sul",
            Local("ESTADUAL", "MS"),
        ),
        (OrgaoInferido("Receita Federal do Brasil", "FEDERAL", None, None), "", Local("NACIONAL")),
        # Federal de um estado só: as vagas são daquele estado.
        (OrgaoInferido("Universidade Federal da Paraíba", "FEDERAL", "PB", None), "", Local("ESTADUAL", "PB")),
        (OrgaoInferido("TRT da 13ª Região", "FEDERAL", None, None), "", Local("ESTADUAL", "PB")),
        # TRT da 8ª Região (Pará e Amapá): mais de um estado, fica nacional.
        (OrgaoInferido("Tribunal Regional do Trabalho da 8ª Região", "FEDERAL", None, None), "", Local("NACIONAL")),
    ],
)
def test_local_resolvido(resolvedor, orgao, contexto, esperado):
    assert resolvedor.resolver(orgao, contexto=contexto) == esperado


def test_homonimo_sem_pista_usa_a_capital_com_aviso(resolvedor):
    local = resolvedor.resolver(OrgaoInferido("Prefeitura de Belém", "MUNICIPAL", None, "Belém"))
    assert (local.abrangencia, local.uf, local.municipio_ibge) == ("MUNICIPAL", "PA", 1501402)
    assert "capital" in local.aviso


def test_sem_informacao_suficiente_fica_sem_abrangencia(resolvedor):
    ambiguo = resolvedor.resolver(OrgaoInferido("Prefeitura de Bom Jesus", "MUNICIPAL", None, "Bom Jesus"))
    assert ambiguo.abrangencia is None and "SC" in ambiguo.aviso and "RS" in ambiguo.aviso

    inexistente = resolvedor.resolver(OrgaoInferido("Prefeitura de Atlântida", "MUNICIPAL", "SC", "Atlântida"))
    assert inexistente.abrangencia is None and "não encontrado" in inexistente.aviso

    sem_uf = resolvedor.resolver(OrgaoInferido("Secretaria de Estado da Saúde", "ESTADUAL", None, None))
    assert sem_uf.abrangencia is None and sem_uf.aviso

    assert resolvedor.resolver(None).aviso == "órgão não identificado: local do concurso desconhecido"


def test_cnu_e_sempre_nacional(resolvedor):
    orgao_estadual = OrgaoInferido("Qualquer", "ESTADUAL", "PB", None)
    assert resolvedor.resolver(orgao_estadual, unificado=True) == Local("NACIONAL")
    assert resolvedor.resolver(None, unificado=True) == Local("NACIONAL")


def test_ufs_citadas():
    assert ufs_citadas("Estado do Rio de Janeiro e Macaé/RJ") == {"RJ"}
    assert ufs_citadas("ESTADO DE MATO GROSSO DO SUL") == {"MS"}
    assert ufs_citadas("Vagas AC - ampla concorrência") == set()  # " - AC" não é Acre


@pytest.mark.parametrize(
    ("titulo", "link", "esperado"),
    [
        ("Concurso Público Nacional Unificado 2", "https://conhecimento.fgv.br/cpnu2", True),
        ("Concurso Nacional Unificado", None, True),
        ("CNU 2026 - Bloco 3", None, True),
        ("Página do concurso", "https://conhecimento.fgv.br/cpnu2", True),
        ("Concurso Público para o INSS", "https://conhecimento.fgv.br/concursos/inss26", False),
        ("Concurso Público para a Prefeitura de Cnudópolis", None, False),
    ],
)
def test_detecta_cnu(titulo, link, esperado):
    assert DetectorCNU.padrao().eh_cnu(titulo, link) is esperado


@pytest.mark.parametrize(
    ("nome", "especialidade", "esperado"),
    [
        ("Professor - Nível Superior", None, "SUPERIOR"),
        ("Assistente Administrativo", "Ensino Médio", "MEDIO"),
        ("Médico", "Pediatria", "SUPERIOR"),
        ("Engenheiro Civil", None, "SUPERIOR"),
        ("Analista Judiciário", "Área Judiciária", "SUPERIOR"),
        # Na dúvida, nada: "Técnico Judiciário" e "Professor" dependem do edital.
        ("Técnico Judiciário", None, None),
        ("Professor", "Anos Iniciais", None),
        ("Motorista", None, None),
    ],
)
def test_escolaridade_inferida_de_forma_conservadora(nome, especialidade, esperado):
    assert InferidorEscolaridade.padrao().inferir(nome, especialidade) == esperado
