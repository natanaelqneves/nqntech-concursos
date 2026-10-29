"""Integração: pipeline completo contra um PostgreSQL migrado, com a FGV simulada (sem internet).

Conecta como coletor_app, exatamente como em produção; um admin só limpa os dados criados pelo teste.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

from coletor.config import Config, ConfigBanco
from coletor.db import Repositorio
from coletor.http_cliente import ClienteHttp
from coletor.pipeline.orquestrador import ETAPAS, Orquestrador, codigo_de_saida

pytestmark = pytest.mark.db

PDFS = Path(__file__).parent / "fixtures" / "pdf"
BASE = "https://conhecimento.fgv.br"
TJPB = f"{BASE}/concursos/tjpb26"
PM = f"{BASE}/concursos/teste-pm"
ARQ = f"{BASE}/sites/default/files/concursos"

LISTAGEM = """<html><body><main>
<div class="view view-concursos-em-andamento"><div class="view-content">
  <div class="views-row">
    <a href="/concursos/tjpb26">Concurso Público para Tribunal de Justiça do Estado da Paraíba</a></div>
  <div class="views-row">
    <a href="/concursos/teste-pm">Concurso Público para a Polícia Militar do Estado do Piauí</a></div>
  <div class="views-row"><a href="/exames/cfc/teste">Exame de Suficiência</a></div>
</div></div></main></body></html>"""

PAGINA_PM = f"""<html><body><main><h1>Concurso Público para a Polícia Militar do Estado do Piauí</h1>
<div class="field field--name-field-concurso-status"><small class="field__item">Em Andamento</small></div>
<div class="field field--name-body"><p>Vagas para Soldado.</p></div>
<div class="field field--name-field-concurso-arquivos"><div class="field__item"><div class="paragraph">
  <time datetime="2026-10-01T12:00:00Z">01/10/2026</time><a href="{ARQ}/teste-pm-edital.pdf">Edital de abertura</a>
</div></div></div></main></body></html>"""


class SiteFGVSimulado:
    def __init__(self, fixture_texto) -> None:
        pagina_tjpb = fixture_texto("fgv/concurso_tjpb26.html")
        self.paginas = {
            "/robots.txt": fixture_texto("fgv/robots.txt"),
            "/concursos": LISTAGEM,
            "/concursos/tjpb26": pagina_tjpb.replace(
                f"{ARQ}/edital-retificado-tjpb_23.10_.pdf", f"{ARQ}/teste-tjpb-edital.pdf"
            ).replace(f"{ARQ}/extrato-1a-retificacao-do-edital-tjpb.pdf", f"{ARQ}/teste-tjpb-ret1.pdf"),
            "/concursos/teste-pm": PAGINA_PM,
        }
        self.pdfs = {
            "/sites/default/files/concursos/teste-tjpb-edital.pdf": (PDFS / "edital_mini_tjpb.pdf").read_bytes(),
            "/sites/default/files/concursos/teste-tjpb-ret1.pdf": (PDFS / "retificacao_mini.pdf").read_bytes(),
            "/sites/default/files/concursos/teste-pm-edital.pdf": (PDFS / "retificacao_mini.pdf").read_bytes()
            + b"\n% outro arquivo\n",
            "/sites/default/files/concursos/teste-tjpb-ret2.pdf": (PDFS / "retificacao_mini.pdf").read_bytes()
            + b"\n% segunda\n",
        }
        self.pdfs_baixados: list[str] = []

    def responder(self, request: httpx.Request) -> httpx.Response:
        caminho = request.url.path
        if caminho in self.pdfs:
            self.pdfs_baixados.append(caminho)
            return httpx.Response(200, content=self.pdfs[caminho], headers={"Content-Type": "application/pdf"})
        if caminho in self.paginas:
            return httpx.Response(200, text=self.paginas[caminho], headers={"Content-Type": "text/html; charset=utf-8"})
        return httpx.Response(404)


@pytest.fixture
def limpar(conn_admin):
    def apagar() -> None:
        conn_admin.execute("DELETE FROM concursos.sinal_descoberta WHERE url = ANY(%s)", ([TJPB, PM],))
        conn_admin.execute("DELETE FROM concursos.concurso WHERE link_oficial = ANY(%s)", ([TJPB, PM],))
        for prefixo in ("https://www.ibam-concursos.org.br/%", "https://portal.ibade.selecao.site/%"):
            conn_admin.execute("DELETE FROM concursos.sinal_descoberta WHERE url LIKE %s", (prefixo,))
            conn_admin.execute("DELETE FROM concursos.concurso WHERE link_oficial LIKE %s", (prefixo,))
        conn_admin.execute(
            """DELETE FROM concursos.orgao o WHERE nome IN ('Tribunal de Justiça do Estado da Paraíba',
                                                        'Polícia Militar do Estado do Piauí')
               AND NOT EXISTS (SELECT 1 FROM concursos.concurso c WHERE c.orgao_id = o.id)"""
        )

    apagar()
    yield
    apagar()


def criar_orquestrador(parametros_coletor, site: SiteFGVSimulado):
    config = Config(
        banco=ConfigBanco(
            host=parametros_coletor["host"],
            porta=int(parametros_coletor["port"]),
            nome=parametros_coletor["dbname"],
            usuario=parametros_coletor["user"],
            senha=parametros_coletor["password"],
            sslmode="disable",
        ),
        contato_email="teste@exemplo.com",
        intervalo_dominio_s=0,
        pdf_max_bytes=5 * 1024 * 1024,
        max_documentos_por_execucao=100,
        max_paginas_listagem=3,
    )
    conn = psycopg.connect(**parametros_coletor, row_factory=dict_row)
    conn.execute("SET search_path = concursos")

    def criar_http(dominios: frozenset[str]) -> ClienteHttp:
        return ClienteHttp(dominios, config.user_agent, intervalo_s=0, transport=httpx.MockTransport(site.responder))

    return conn, Orquestrador(config, Repositorio(conn), criar_http)


def test_pipeline_completo_idempotente_e_detecta_retificacao(parametros_coletor, conn_admin, limpar, fixture_texto):
    site = SiteFGVSimulado(fixture_texto)
    conn, orquestrador = criar_orquestrador(parametros_coletor, site)
    consulta = conn_admin.cursor(row_factory=dict_row)

    # 1ª execução: tudo novo
    resumos = orquestrador.executar(ETAPAS, fonte="fgv")
    assert codigo_de_saida(resumos) == 0, resumos
    assert {r.etapa: r.status for r in resumos} == {
        "DESCOBERTA": "SUCESSO",
        "VINCULACAO": "SUCESSO",
        "DOCUMENTOS": "SUCESSO",
        "ESTRUTURACAO": "SUCESSO",
    }

    tjpb = consulta.execute(
        """SELECT c.*, o.nome AS orgao, o.uf, o.esfera, b.sigla AS banca FROM concursos.concurso c
           JOIN concursos.orgao o ON o.id = c.orgao_id JOIN concursos.banca b ON b.id = c.banca_id
           WHERE link_oficial = %s""",
        (TJPB,),
    ).fetchone()
    assert (tjpb["orgao"], tjpb["uf"], tjpb["esfera"], tjpb["banca"]) == (
        "Tribunal de Justiça do Estado da Paraíba",
        "PB",
        "ESTADUAL",
        "FGV",
    )
    assert (tjpb["numero_edital"], str(tjpb["inscricao_fim"]), str(tjpb["data_prova"])) == (
        "01/2026",
        "2026-11-18",
        "2027-01-24",
    )
    assert tjpb["situacao"] in ("INSCRICOES_ABERTAS", "EM_ANDAMENTO")
    assert tjpb["link_inscricao"] == "https://portal.conhecimento.fgv.br/Concurso/Inscricao"

    cargos = consulta.execute(
        "SELECT especialidade, vagas FROM concursos.cargo WHERE concurso_id = %s", (tjpb["id"],)
    ).fetchall()
    assert len(cargos) == 9
    assert {"TI – Desenvolvimento de Sistemas", "TI – Banco de Dados"} <= {c["especialidade"] for c in cargos}

    docs = consulta.execute(
        "SELECT tipo, status_extracao, hash_sha256 FROM concursos.documento WHERE concurso_id = %s ORDER BY tipo",
        (tjpb["id"],),
    ).fetchall()
    assert [(d["tipo"], d["status_extracao"]) for d in docs] == [("EDITAL", "OK"), ("RETIFICACAO", "OK")]
    assert all(len(d["hash_sha256"]) == 64 for d in docs)

    pm = consulta.execute("SELECT avisos_extracao FROM concursos.concurso WHERE link_oficial = %s", (PM,)).fetchone()
    assert any("quadro de cargos" in a for a in pm["avisos_extracao"])

    # 2ª execução: nada muda, nenhum PDF é baixado de novo
    site.pdfs_baixados.clear()
    resumos = orquestrador.executar(ETAPAS, fonte="fgv")
    assert next(r for r in resumos if r.etapa == "DESCOBERTA").itens_novos == 0
    assert site.pdfs_baixados == []
    assert (
        consulta.execute(
            "SELECT count(*) AS n FROM concursos.documento WHERE concurso_id = %s", (tjpb["id"],)
        ).fetchone()["n"]
        == 2
    )

    # 3ª execução: a banca publica a 2ª retificação → novo documento no mesmo concurso
    site.paginas["/concursos/tjpb26"] = site.paginas["/concursos/tjpb26"].replace(
        "Arquivos do concurso</h3>",
        'Arquivos do concurso</h3><div class="field__item"><div class="paragraph">'
        f'<time datetime="2026-11-05T12:00:00Z">05/11/2026</time><a href="{ARQ}/teste-tjpb-ret2.pdf">2ª Retificação</a>'
        "</div></div>",
        1,
    )
    orquestrador.executar(ETAPAS, fonte="fgv")
    novos = consulta.execute(
        "SELECT tipo, status_extracao FROM concursos.documento WHERE concurso_id = %s AND url_origem LIKE '%%ret2.pdf'",
        (tjpb["id"],),
    ).fetchall()
    assert [(d["tipo"], d["status_extracao"]) for d in novos] == [("RETIFICACAO", "OK")]
    assert (
        consulta.execute("SELECT count(*) AS n FROM concursos.concurso WHERE link_oficial = %s", (TJPB,)).fetchone()[
            "n"
        ]
        == 1
    )
    conn.close()


def test_falha_total_da_fonte_e_registrada(parametros_coletor, conn_admin, limpar, fixture_texto):
    site = SiteFGVSimulado(fixture_texto)
    site.paginas["/concursos"] = "<html>fora do ar</html>"
    conn, orquestrador = criar_orquestrador(parametros_coletor, site)

    resumos = orquestrador.executar(("descobrir",), fonte="fgv")

    assert codigo_de_saida(resumos) == 1
    ultima = conn_admin.execute(
        "SELECT status, mensagem_erro FROM concursos.execucao_coleta"
        " WHERE etapa = 'DESCOBERTA' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert ultima[0] == "FALHA" and "layout" in ultima[1]
    conn.close()


class SiteIBAMeIBADESimulado:
    """Páginas reais capturadas em 29/10/2026, com um cargo enxertado em cada banca para conferir a estruturação."""

    def __init__(self, fixture_texto) -> None:
        self.ibam = fixture_texto("ibam/abertas.html").replace("CONTROLADOR INTERNO", "ANALISTA DE SISTEMAS")
        self.ibade_lista = fixture_texto("ibade/lista.html")
        self.ibade = {
            "/edital/ver/128": fixture_texto("ibade/edital_128.html"),
            "/edital/ver/129": fixture_texto("ibade/edital_129.html").replace("CONTADOR I", "PROGRAMADOR I"),
        }
        self.pdf = (PDFS / "retificacao_mini.pdf").read_bytes()
        self.pdfs_baixados: list[str] = []

    def responder(self, request: httpx.Request) -> httpx.Response:
        host, caminho = request.url.host, request.url.path
        if caminho == "/robots.txt":
            return httpx.Response(404)
        if host == "www.ibam-concursos.org.br" and caminho == "/default.asp":
            return httpx.Response(200, text=self.ibam, headers={"Content-Type": "text/html; charset=utf-8"})
        if host == "portal.ibade.selecao.site" and caminho == "/edital":
            return httpx.Response(200, text=self.ibade_lista, headers={"Content-Type": "text/html; charset=utf-8"})
        if host == "portal.ibade.selecao.site" and caminho in self.ibade:
            return httpx.Response(200, text=self.ibade[caminho], headers={"Content-Type": "text/html; charset=utf-8"})
        if caminho.endswith(".pdf") or caminho == "/arquivo.php":
            self.pdfs_baixados.append(str(request.url))
            # Cada URL vira um PDF diferente (hash distinto), como na vida real.
            return httpx.Response(
                200, content=self.pdf + str(request.url).encode(), headers={"Content-Type": "application/pdf"}
            )
        return httpx.Response(404)


def test_fontes_com_dados_estruturados_ibam_e_ibade(parametros_coletor, conn_admin, limpar, fixture_texto):
    site = SiteIBAMeIBADESimulado(fixture_texto)
    conn, orquestrador = criar_orquestrador(parametros_coletor, site)  # type: ignore[arg-type]
    consulta = conn_admin.cursor(row_factory=dict_row)

    resumos = orquestrador.executar(ETAPAS)
    descobertas = {r.fonte: r for r in resumos if r.etapa == "DESCOBERTA"}
    # IBADE: 9 concursos na lista, só 2 páginas simuladas → PARCIAL (as outras 7 dão 404), sem derrubar nada.
    assert descobertas["ibam"].status == "SUCESSO" and descobertas["ibam"].itens_novos == 4
    assert descobertas["ibade"].status == "PARCIAL" and descobertas["ibade"].itens_novos == 2

    fraiburgo = consulta.execute(
        """SELECT c.*, o.nome AS orgao, o.uf, o.municipio, o.esfera, b.sigla AS banca FROM concursos.concurso c
           JOIN concursos.orgao o ON o.id = c.orgao_id JOIN concursos.banca b ON b.id = c.banca_id
           WHERE c.titulo = 'Camara de Fraiburgo/SC - Ed.01/2026 - CP'"""
    ).fetchone()
    assert (fraiburgo["orgao"], fraiburgo["uf"], fraiburgo["municipio"], fraiburgo["esfera"], fraiburgo["banca"]) == (
        "Camara de Fraiburgo",
        "SC",
        "Fraiburgo",
        "MUNICIPAL",
        "IBAM",
    )
    assert (fraiburgo["origem_estrutura"], fraiburgo["numero_edital"]) == ("FONTE", "01/2026")
    assert (str(fraiburgo["inscricao_fim"]), str(fraiburgo["data_prova"]), str(fraiburgo["taxa_max"])) == (
        "2026-11-05",
        "2026-11-29",
        "130.00",
    )
    cargos = consulta.execute(
        "SELECT nome, escolaridade, vagas FROM concursos.cargo WHERE concurso_id = %s", (fraiburgo["id"],)
    ).fetchall()
    assert ("Analista de Sistemas", "SUPERIOR", 1) in [(c["nome"], c["escolaridade"], c["vagas"]) for c in cargos]

    # Todo concurso ativo tem o edital baixado e lido (todas as áreas interessam ao site).
    docs = {
        d["titulo"]: d["status_extracao"]
        for d in consulta.execute(
            "SELECT titulo, status_extracao FROM concursos.documento WHERE concurso_id = %s", (fraiburgo["id"],)
        )
    }
    assert docs["Edital de Abertura"] == "OK"
    assert [u for u in site.pdfs_baixados if "spslag" in u]  # Lages: área sem relação com TI também é baixada

    cref = consulta.execute(
        """SELECT c.situacao, c.avisos_extracao, o.uf FROM concursos.concurso c
           JOIN concursos.orgao o ON o.id = c.orgao_id WHERE c.link_oficial = %s""",
        ("https://portal.ibade.selecao.site/edital/ver/129",),
    ).fetchone()
    assert (cref["situacao"], cref["uf"]) == ("EM_ANDAMENTO", "ES")
    assert any("só no edital" in a for a in cref["avisos_extracao"])

    # 2ª execução: nada muda (concurso não é "tocado" sem mudança real, nenhum PDF baixado de novo)
    antes = consulta.execute(
        "SELECT atualizado_em FROM concursos.concurso WHERE id = %s", (fraiburgo["id"],)
    ).fetchone()
    site.pdfs_baixados.clear()
    orquestrador.executar(ETAPAS)
    depois = consulta.execute(
        "SELECT atualizado_em FROM concursos.concurso WHERE id = %s", (fraiburgo["id"],)
    ).fetchone()
    assert antes == depois
    assert site.pdfs_baixados == []
    conn.close()
