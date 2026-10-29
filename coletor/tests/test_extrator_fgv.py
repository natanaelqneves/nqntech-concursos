from datetime import date
from decimal import Decimal

from coletor.extratores.fgv import ExtratorFGV


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
