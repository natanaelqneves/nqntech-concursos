from pathlib import Path

import pytest

from coletor.pipeline.documentos import ExtracaoFalhou, extrair_texto_pdf
from coletor.pipeline.vinculacao import classificar_tipo_documento, eh_pdf

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
