"""Integração do fluxo único contra o banco migrado (como coletor_app, sem internet):
busca na web → pré-cadastro → edital achado na página oficial e baixado → leitura confere/completa → site;
edital enviado pelo Drive com o código; fonte da banca adotando o pré-cadastro sem duplicar."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

from coletor.config import Config, ConfigBanco
from coletor.db import Repositorio
from coletor.fontes.base import SinalDescoberta
from coletor.fontes.busca_ia import sinal_da_sugestao
from coletor.http_cliente import ClienteHttp
from coletor.ia.busca_web import Sugestao
from coletor.importacao_manual import anexar_ao_concurso, ler_pdf
from coletor.pipeline.orquestrador import Orquestrador

pytestmark = pytest.mark.db

PDFS = Path(__file__).parent / "fixtures" / "pdf"
PAGINA = "https://teste-fluxo.pb.gov.br/concurso-2026"
SEM_EDITAL = "https://teste-fluxo.pb.gov.br/sem-edital"
FGV_URL = "https://conhecimento.fgv.br/concursos/teste-fluxo"
ORGAO = "Tribunal de Justiça do Estado da Paraíba"


def sugestao(pagina: str, **campos) -> Sugestao:
    hoje = date.today()
    base = dict(
        alvo="nordeste", orgao=ORGAO, banca="FGV", esfera="ESTADUAL", uf="PB", municipio=None, situacao="ABERTO",
        ano=2026, inscricoes_inicio=None, inscricoes_fim=hoje + timedelta(days=30), isencao_inicio=None,
        isencao_fim=None, data_prova=None, taxa_max=Decimal("99.00"), vagas=50, salario_max=None,
        cargos=("Analista Judiciário",), escolaridades=("SUPERIOR",), link_pagina=pagina, link_edital=None,
        oficial=True, confirmado=True,
    )  # fmt: skip
    base.update(campos)
    return Sugestao(**base)


class SiteSimulado:
    def __init__(self) -> None:
        self.paginas = {
            "/concurso-2026": '<a href="/arquivos/resultado.pdf">Resultado</a>'
            '<a href="/arquivos/edital-abertura.pdf">Edital de Abertura</a>',
            "/sem-edital": "<p>Edital em breve</p>",
        }
        self.pdfs = {"/arquivos/edital-abertura.pdf": (PDFS / "edital_mini_tjpb.pdf").read_bytes()}
        self.baixados: list[str] = []

    def responder(self, request: httpx.Request) -> httpx.Response:
        caminho = request.url.path
        if caminho in self.pdfs:
            self.baixados.append(caminho)
            return httpx.Response(200, content=self.pdfs[caminho], headers={"Content-Type": "application/pdf"})
        if caminho in self.paginas:
            return httpx.Response(200, text=self.paginas[caminho], headers={"Content-Type": "text/html; charset=utf-8"})
        return httpx.Response(404)


@pytest.fixture
def limpar(conn_admin):
    def apagar() -> None:
        links = [PAGINA, SEM_EDITAL, FGV_URL]
        conn_admin.execute("DELETE FROM concursos.sinal_descoberta WHERE url = ANY(%s)", (links,))
        conn_admin.execute("DELETE FROM concursos.concurso WHERE link_oficial = ANY(%s)", (links,))
        conn_admin.execute(
            """DELETE FROM concursos.orgao o WHERE nome = %s
               AND NOT EXISTS (SELECT 1 FROM concursos.concurso c WHERE c.orgao_id = o.id)""",
            (ORGAO,),
        )

    apagar()
    yield
    apagar()


@pytest.fixture
def ambiente(parametros_coletor):
    site = SiteSimulado()
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
        max_paginas_listagem=1,
    )
    conn = psycopg.connect(**parametros_coletor, row_factory=dict_row)
    conn.execute("SET search_path = concursos")

    def criar_http(dominios: frozenset[str]) -> ClienteHttp:
        return ClienteHttp(dominios, config.user_agent, intervalo_s=0, transport=httpx.MockTransport(site.responder),
                           resolver=lambda host: ["93.184.216.34"])  # fmt: skip

    repo = Repositorio(conn)
    yield site, repo, Orquestrador(config, repo, criar_http)
    conn.close()


def gravar(repo: Repositorio, fonte: str, sinal: SinalDescoberta) -> None:
    fonte_id = repo.conn.execute("SELECT id FROM fonte WHERE nome = %s", (fonte,)).fetchone()["id"]
    with repo.transacao():
        repo.gravar_sinal(fonte_id, sinal)


def concurso(conn_admin, link: str):
    return conn_admin.execute(
        "SELECT * FROM concursos.concurso WHERE link_oficial = %s", (link,), prepare=False
    ).fetchone()


def test_pre_cadastro_espera_o_edital_e_o_edital_vence(ambiente, conn_admin, limpar):
    site, repo, orquestrador = ambiente
    conn_admin.row_factory = dict_row
    gravar(repo, "busca-ia", sinal_da_sugestao(sugestao(PAGINA), date.today()))

    orquestrador.executar(("vincular", "classificar", "resumir"))
    antes = concurso(conn_admin, PAGINA)
    assert antes["situacao"] == "INSCRICOES_ABERTAS" and antes["abrangencia"] == "ESTADUAL"
    assert antes["publicado"] is False  # aberto sem edital lido não vai ao site
    busca = conn_admin.execute("SELECT * FROM concursos.concurso_busca WHERE concurso_id = %s", (antes["id"],))
    assert busca.fetchone()["dados"]["taxa_max"] == "99.00"

    resumos = orquestrador.executar(("localizar", "documentos", "estruturar", "classificar", "resumir"))
    assert {r.etapa: r.status for r in resumos}["LOCALIZACAO"] == "SUCESSO"
    assert site.baixados == ["/arquivos/edital-abertura.pdf"]
    documento = conn_admin.execute(
        "SELECT url_origem, oficial, status_extracao FROM concursos.documento WHERE concurso_id = %s", (antes["id"],)
    ).fetchone()
    assert (documento["url_origem"], documento["oficial"], documento["status_extracao"]) == (
        "https://teste-fluxo.pb.gov.br/arquivos/edital-abertura.pdf",
        True,
        "OK",
    )
    depois = concurso(conn_admin, PAGINA)
    # Edital do TJPB (mini): inscrições até 18/11/2026 e prova em 24/01/2027 vêm do edital, não da busca.
    assert (str(depois["inscricao_fim"]), str(depois["data_prova"])) == ("2026-11-18", "2027-01-24")
    assert depois["origem_estrutura"] == "EDITAL" and depois["taxa_max"] != Decimal("99.00")
    assert depois["publicado"] is (depois["situacao"] == "INSCRICOES_ABERTAS")


def test_edital_pelo_drive_com_o_codigo_e_pendencias(ambiente, conn_admin, limpar):
    _, repo, orquestrador = ambiente
    conn_admin.row_factory = dict_row
    gravar(repo, "busca-ia", sinal_da_sugestao(sugestao(SEM_EDITAL), date.today()))
    orquestrador.executar(("vincular", "localizar"))
    pre = concurso(conn_admin, SEM_EDITAL)
    pendentes = [linha["id"] for linha in repo.aguardando_edital()]
    repo.conn.commit()
    assert pre["id"] in pendentes
    falha = conn_admin.execute(
        "SELECT edital_falha FROM concursos.concurso_busca WHERE concurso_id = %s", (pre["id"],)
    ).fetchone()["edital_falha"]
    assert "nenhum PDF de edital" in falha

    lido = anexar_ao_concurso(repo, pre["id"], ler_pdf(PDFS / "edital_mini_tjpb.pdf", 5 * 1024 * 1024, None))
    assert lido.status == "OK"
    assert pre["id"] not in [linha["id"] for linha in repo.aguardando_edital()]
    repo.conn.commit()
    documento = conn_admin.execute(
        "SELECT oficial, status_extracao FROM concursos.documento WHERE concurso_id = %s", (pre["id"],)
    ).fetchone()
    assert (documento["oficial"], documento["status_extracao"]) == (False, "OK")
    assert anexar_ao_concurso(repo, 999_999_999, lido).status == "FALHA"

    orquestrador.executar(("estruturar", "classificar", "resumir"))
    assert concurso(conn_admin, SEM_EDITAL)["origem_estrutura"] == "EDITAL"


def test_fonte_da_banca_adota_o_pre_cadastro_sem_duplicar(ambiente, conn_admin, limpar):
    _, repo, orquestrador = ambiente
    conn_admin.row_factory = dict_row
    gravar(repo, "busca-ia", sinal_da_sugestao(sugestao(SEM_EDITAL), date.today()))
    orquestrador.executar(("vincular",))
    pre = concurso(conn_admin, SEM_EDITAL)

    gravar(repo, "fgv", SinalDescoberta(titulo=f"Concurso Público para {ORGAO}", url=FGV_URL, payload={}))
    orquestrador.executar(("vincular",))
    adotado = concurso(conn_admin, FGV_URL)
    assert adotado is not None and adotado["id"] == pre["id"]
    assert concurso(conn_admin, SEM_EDITAL) is None

    # A busca acha de novo o mesmo concurso (outra página): só atualiza o pré-cadastro, não cria outro.
    gravar(repo, "busca-ia", sinal_da_sugestao(sugestao(SEM_EDITAL, taxa_max=Decimal("10.00")), date.today()))
    orquestrador.executar(("vincular",))
    dados = conn_admin.execute(
        "SELECT dados FROM concursos.concurso_busca WHERE concurso_id = %s", (pre["id"],)
    ).fetchone()["dados"]
    assert dados["taxa_max"] == "10.00"
    total = conn_admin.execute(
        "SELECT count(*) AS n FROM concursos.concurso WHERE link_oficial = ANY(%s)", ([SEM_EDITAL, FGV_URL],)
    ).fetchone()["n"]
    assert total == 1
