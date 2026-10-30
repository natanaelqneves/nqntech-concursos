from datetime import date
from decimal import Decimal

import pytest

from coletor.extratores.fgv import ExtratorFGV, nome_de_cargo_plausivel


def test_edital_tjpb_2026_real(fixture_texto):
    edital = ExtratorFGV().extrair(fixture_texto("fgv/edital_tjpb26_1.txt"))

    assert edital.numero_edital == "01/2026"
    assert edital.ano == 2026
    assert edital.orgao == "Tribunal de Justiça do Estado da Paraíba"
    assert edital.inscricao_inicio == date(2026, 10, 20)
    assert edital.inscricao_fim == date(2026, 11, 18)
    assert edital.data_prova == date(2027, 1, 24)
    assert edital.taxa_min == edital.taxa_max == Decimal("120.00")
    assert edital.avisos == ()

    especialidades = {c.especialidade: c for c in edital.cargos}
    assert len(edital.cargos) == 9
    assert set(especialidades) >= {
        "TI – Desenvolvimento de Sistemas",  # nome quebrado em duas linhas no PDF
        "TI – Gestão de Governança de TI",
        "TI – Ciência e Análise de Dados",
        "Judiciária",
        "Contabilidade",
    }
    dev = especialidades["TI – Desenvolvimento de Sistemas"]
    assert (dev.nome, dev.vagas, dev.salario, dev.escolaridade) == ("Analista", 10, Decimal("7526.14"), "SUPERIOR")
    assert sum(c.vagas or 0 for c in edital.cargos) == 50  # bate com a linha TOTAL do edital


def test_retificacao_nao_e_edital_completo(fixture_texto):
    edital = ExtratorFGV().extrair(fixture_texto("fgv/edital_tjpb26_0.txt"))
    assert "período de inscrição não encontrado" in edital.avisos


def test_texto_vazio_gera_avisos_e_nao_quebra():
    edital = ExtratorFGV().extrair("")
    assert edital.cargos == ()
    assert len(edital.avisos) >= 4


def test_tabela_sem_coluna_de_remuneracao_e_cadastro_reserva():
    texto = "\n".join(
        [
            "EDITAL Nº 3/2026",
            "NÍVEL MÉDIO",
            "REMUNERAÇÃO: R$ 3.100,00",
            "Cargo Vagas AC PCD",
            "Técnico em Informática 4 3 1",
            "Assistente Administrativo CR CR CR",
            "TOTAL 4 3 1",
            "As inscrições estarão abertas no período de 01/12/2026 a 15/12/2026.",
            "O valor da taxa de inscrição é de R$ 75,50.",
            "As provas objetivas serão realizadas na data provável de 10 de janeiro de 2027.",
        ]
    )
    edital = ExtratorFGV().extrair(texto)

    assert edital.numero_edital == "03/2026"
    tecnico, assistente = edital.cargos
    assert (tecnico.nome, tecnico.vagas, tecnico.salario, tecnico.escolaridade) == (
        "Técnico em Informática",
        4,
        Decimal("3100.00"),
        "MEDIO",
    )
    assert assistente.cadastro_reserva and assistente.vagas is None
    assert (edital.inscricao_inicio, edital.inscricao_fim) == (date(2026, 12, 1), date(2026, 12, 15))
    assert edital.data_prova == date(2027, 1, 10)
    assert edital.taxa_min == Decimal("75.50")


# Editais reais de outras áreas (capturados em 29/10/2026). O quadro de vagas desses editais não sai legível do
# PDF, então os cargos vêm das estratégias alternativas: o importante é o nome (para a área) e o aviso.


def test_ses_to_2026_cargos_pelo_anexo_de_remuneracao(fixture_texto):
    edital = ExtratorFGV().extrair(fixture_texto("fgv/edital_sesto26_0.txt"))

    cargos = {(c.nome, c.especialidade): c for c in edital.cargos}
    assert len(cargos) > 50
    assert cargos[("Enfermeiro Obstetra", None)].salario == Decimal("8421.31")
    assert ("Inspetor em Vigilância Sanitária", "Farmacêutico") in cargos
    assert ("Médico RQE", "Ortopedista Traumatologista") in cargos  # travessão também separa a especialidade
    assert "vagas de cada cargo não identificadas: confira o edital" in edital.avisos
    assert all(c.vagas is None for c in edital.cargos)


def test_dataprev_2026_cargos_pelos_titulos_do_anexo(fixture_texto):
    edital = ExtratorFGV().extrair(fixture_texto("fgv/edital_dataprev26_0.txt"))

    perfis = {c.especialidade for c in edital.cargos if c.nome == "Analista de Tecnologia da Informação"}
    assert "Desenvolvimento de Software" in perfis
    assert "Advocacia" in perfis
    assert "Arquitetura, Engenharia e Sustentação Tecnológica" in perfis  # perfil quebrado em duas linhas
    assert "Analista de Processamento" in {c.nome for c in edital.cargos}
    assert not any("Todos" in c.nome for c in edital.cargos)
    assert "vagas e salários de cada cargo não identificados: confira o edital" in edital.avisos


def test_prefeitura_do_salvador_2026_titulos_com_nivel(fixture_texto):
    edital = ExtratorFGV().extrair(fixture_texto("fgv/edital_pms2026_0.txt"))

    assert {(c.nome, c.escolaridade) for c in edital.cargos} == {
        ("Coordenador Pedagógico I", "SUPERIOR"),
        ("Professor Municipal I", "SUPERIOR"),
    }


def test_pcpr_2026_cargos_da_abertura(fixture_texto):
    edital = ExtratorFGV().extrair(fixture_texto("fgv/edital_pcpr26_0.txt"))

    # O texto da tabela por macrorregião não pode virar "cargo".
    assert [c.nome for c in edital.cargos] == [
        "Delegado de Polícia",
        "Agente de Polícia Judiciária",
        "Papiloscopista Policial",
    ]
    assert edital.orgao == "Polícia Civil do Paraná"


def test_seduc_pa_2026_cargos_da_abertura(fixture_texto):
    edital = ExtratorFGV().extrair(fixture_texto("fgv/edital_seducpa26_0.txt"))
    assert [c.nome for c in edital.cargos] == ["Professor", "Especialista em Educação"]


@pytest.mark.parametrize(
    ("nome", "plausivel"),
    [
        ("Enfermeiro Obstetra", True),
        ("Técnico em Imobilização Ortopédica", True),
        ("vagas por macrorregião de", False),
        ("Todas as vagas que posteriormente Delegado", False),
        ("âmbito da administração direta", False),
        ("Professor 2", False),
        ("Analista de Tecnologia da Informação (Todos os perfis)", False),
    ],
)
def test_nome_de_cargo_plausivel(nome, plausivel):
    assert nome_de_cargo_plausivel(nome) is plausivel
