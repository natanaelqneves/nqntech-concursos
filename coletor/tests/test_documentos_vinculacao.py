from pathlib import Path

import pytest

from coletor.pipeline.documentos import ExtracaoFalhou, extrair_texto_pdf
from coletor.pipeline.vinculacao import classificar_tipo_documento, eh_pdf, inferir_orgao

PDFS = Path(__file__).parent / "fixtures" / "pdf"


@pytest.mark.parametrize(
    ("titulo", "tipo"),
    [
        ("Edital (retificado em 26/10/2026)", "EDITAL"),
        ("Edital de Abertura", "EDITAL"),
        ("1ª Retificação", "RETIFICACAO"),
        ("Extrato da 2ª retificação do edital", "RETIFICACAO"),
        ("Edital de convocação para a prova discursiva", "COMUNICADO"),
        ("Gabarito preliminar", "COMUNICADO"),
        ("Resultado final", "COMUNICADO"),
        ("Anexo III - Atribuições", "OUTRO"),
    ],
)
def test_tipo_do_documento_pelo_titulo(titulo, tipo):
    assert classificar_tipo_documento(titulo) == tipo


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
    ],
)
def test_orgao_inferido_do_titulo(titulo, nome, esfera, uf, municipio):
    orgao = inferir_orgao(titulo)
    assert orgao is not None
    assert (orgao.nome, orgao.esfera, orgao.uf, orgao.municipio) == (nome, esfera, uf, municipio)


def test_eh_pdf():
    assert eh_pdf("https://x.br/a/Edital.PDF?v=2")
    assert not eh_pdf("https://portal.conhecimento.fgv.br/Concurso/Inscricao")


def test_extrai_texto_de_pdf_real():
    texto = extrair_texto_pdf(PDFS / "edital_mini_tjpb.pdf")
    assert "EDITAL Nº 01/2026" in texto
    assert "TI – Banco de Dados" in texto


def test_pdf_escaneado_vem_sem_texto():
    assert extrair_texto_pdf(PDFS / "escaneado.pdf").strip() == ""


@pytest.mark.parametrize(
    ("arquivo", "mensagem"), [("protegido.pdf", "senha"), ("corrompido.pdf", "corrompido|ilegível")]
)
def test_pdf_problematico_nao_derruba(arquivo, mensagem):
    with pytest.raises(ExtracaoFalhou, match=mensagem):
        extrair_texto_pdf(PDFS / arquivo)
