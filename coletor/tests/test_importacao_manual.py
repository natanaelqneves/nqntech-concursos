"""Importação manual: mesmas regras dos PDFs baixados (limites, assinatura, escaneado, protegido) e mesmo pipeline."""

import shutil
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from coletor.db import Repositorio
from coletor.importacao_manual import (
    ImportacaoInvalida,
    importar_pasta,
    ler_pdf,
    link_do_arquivo,
    sinal_do_pdf,
    titulo_do_arquivo,
)

PDFS = Path(__file__).parent / "fixtures" / "pdf"
MB = 1024 * 1024


def _copiar(destino: Path, *nomes: str) -> None:
    for nome in nomes:
        shutil.copy(PDFS / nome, destino / nome)


def test_mesmas_regras_dos_pdfs_baixados(tmp_path):
    _copiar(tmp_path, "edital_mini_tjpb.pdf", "escaneado.pdf", "protegido.pdf", "corrompido.pdf")
    (tmp_path / "falso.pdf").write_text("<html>não sou PDF</html>")
    lidos = {p: ler_pdf(tmp_path / p, 5 * MB, None) for p in [
        "edital_mini_tjpb.pdf", "escaneado.pdf", "protegido.pdf", "corrompido.pdf", "falso.pdf"]}  # fmt: skip
    assert lidos["edital_mini_tjpb.pdf"].status == "OK"
    assert lidos["escaneado.pdf"].status == "SEM_TEXTO"
    assert lidos["protegido.pdf"].status == "FALHA" and "senha" in lidos["protegido.pdf"].motivo
    assert lidos["corrompido.pdf"].status == "FALHA"
    assert lidos["falso.pdf"].status == "FALHA" and "%PDF-" in lidos["falso.pdf"].motivo
    assert ler_pdf(tmp_path / "edital_mini_tjpb.pdf", 10, None).status == "FALHA"  # acima do limite


def test_link_lateral_e_validado(tmp_path):
    pdf = tmp_path / "edital.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert link_do_arquivo(pdf, None) is None
    assert link_do_arquivo(pdf, "https://www.fcc.org.br/concurso/x") == "https://www.fcc.org.br/concurso/x"
    (tmp_path / "edital.url").write_text("https://www.vunesp.com.br/abc\n")
    assert link_do_arquivo(pdf, "https://outro") == "https://www.vunesp.com.br/abc"
    (tmp_path / "edital.url").write_text("javascript:alert(1)")
    with pytest.raises(ImportacaoInvalida):
        link_do_arquivo(pdf, None)


def test_sinal_usa_o_link_e_identifica_o_arquivo_pelo_hash(tmp_path):
    _copiar(tmp_path, "edital_mini_tjpb.pdf")
    pdf = ler_pdf(tmp_path / "edital_mini_tjpb.pdf", 5 * MB, "https://exemplo.gov.br/concurso")
    sinal = sinal_do_pdf(pdf)
    assert sinal.url == "https://exemplo.gov.br/concurso"
    [arquivo] = sinal.payload["arquivos"]
    assert arquivo["url"] == f"manual:{pdf.sha256}" and arquivo["tipo"] == "EDITAL"
    assert titulo_do_arquivo(Path("Retificacao_01-2026.pdf")) == "Retificacao 01 2026"


@pytest.mark.db
def test_importacao_passa_pelo_pipeline(parametros_coletor, conn_admin, tmp_path):
    link = "https://exemplo.gov.br/teste-importacao-manual"
    conn_admin.execute("DELETE FROM concursos.sinal_descoberta WHERE url = %s", (link,))
    conn_admin.execute("DELETE FROM concursos.concurso WHERE link_oficial = %s", (link,))
    _copiar(tmp_path, "edital_mini_tjpb.pdf", "protegido.pdf")
    conn = psycopg.connect(**parametros_coletor, row_factory=dict_row)
    conn.execute("SET search_path = concursos")
    repo = Repositorio(conn)
    try:
        with pytest.raises(ImportacaoInvalida):
            importar_pasta(repo, tmp_path, "NAO-EXISTE", link, 5 * MB)
        resumo = importar_pasta(repo, tmp_path, "FCC", link, 5 * MB)
        assert resumo.status == "PARCIAL" and resumo.itens_novos == 1  # o protegido falha, o outro segue
        importar_pasta(repo, tmp_path, "FCC", link, 5 * MB)  # idempotente
        documentos = conn_admin.execute(
            """SELECT d.status_extracao, d.tipo, length(d.texto_extraido) > 200 AS com_texto
               FROM concursos.documento d JOIN concursos.concurso c ON c.id = d.concurso_id
               WHERE c.link_oficial = %s""",
            (link,),
        ).fetchall()
        assert documentos == [("OK", "EDITAL", True)]
        fonte = conn_admin.execute(
            """SELECT f.nome, f.ativa FROM concursos.sinal_descoberta s JOIN concursos.fonte f ON f.id = s.fonte_id
               WHERE s.url = %s""",
            (link,),
        ).fetchone()
        assert fonte == ("manual-fcc", False)
    finally:
        conn.close()
        conn_admin.execute("DELETE FROM concursos.sinal_descoberta WHERE url = %s", (link,))
        conn_admin.execute("DELETE FROM concursos.concurso WHERE link_oficial = %s", (link,))
