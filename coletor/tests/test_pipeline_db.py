"""Integração: pipeline completo contra um PostgreSQL migrado, com a FGV simulada (sem internet).

Conecta como coletor_app, exatamente como em produção; um admin só limpa os dados criados pelo teste.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import psycopg
import pytest
import yaml
from psycopg.rows import dict_row

from coletor.config import Config, ConfigBanco
from coletor.db import Repositorio
from coletor.extratores.fgv import ExtratorFGV
from coletor.http_cliente import ClienteHttp
from coletor.pipeline.orquestrador import ETAPAS, Orquestrador, codigo_de_saida

pytestmark = pytest.mark.db

PDFS = Path(__file__).parent / "fixtures" / "pdf"
BASE = "https://conhecimento.fgv.br"
TJPB = f"{BASE}/concursos/tjpb26"
PM = f"{BASE}/concursos/teste-pm"
ANTIGO = f"{BASE}/concursos/teste-antigo"
RECENTE = f"{BASE}/concursos/teste-recente"
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
        self.paginas_lidas: list[str] = []

    def responder(self, request: httpx.Request) -> httpx.Response:
        caminho = request.url.path
        self.paginas_lidas.append(caminho)
        if caminho in self.pdfs:
            self.pdfs_baixados.append(caminho)
            return httpx.Response(200, content=self.pdfs[caminho], headers={"Content-Type": "application/pdf"})
        if caminho in self.paginas:
            return httpx.Response(200, text=self.paginas[caminho], headers={"Content-Type": "text/html; charset=utf-8"})
        return httpx.Response(404)


@pytest.fixture
def limpar(conn_admin):
    def apagar() -> None:
        urls = [TJPB, PM, ANTIGO, RECENTE]
        conn_admin.execute("DELETE FROM concursos.sinal_descoberta WHERE url = ANY(%s)", (urls,))
        conn_admin.execute("DELETE FROM concursos.concurso WHERE link_oficial = ANY(%s)", (urls,))
        for prefixo in ("https://www.ibam-concursos.org.br/%", "https://portal.ibade.selecao.site/%"):
            conn_admin.execute("DELETE FROM concursos.sinal_descoberta WHERE url LIKE %s", (prefixo,))
            conn_admin.execute("DELETE FROM concursos.concurso WHERE link_oficial LIKE %s", (prefixo,))
        conn_admin.execute(
            """DELETE FROM concursos.orgao o WHERE nome IN ('Tribunal de Justiça do Estado da Paraíba',
                                                        'Polícia Militar do Estado do Piauí',
                                                        'Câmara Municipal de Taubaté',
                                                        'Tribunal Regional do Trabalho da 16ª Região')
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
        max_paginas_realizados=2,
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
        "CLASSIFICACAO": "SUCESSO",
        "RESUMO": "SUCESSO",
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
        "SELECT especialidade, vagas, area FROM concursos.cargo WHERE concurso_id = %s", (tjpb["id"],)
    ).fetchall()
    assert len(cargos) == 9
    assert {"TI – Desenvolvimento de Sistemas", "TI – Banco de Dados"} <= {c["especialidade"] for c in cargos}
    areas = {c["especialidade"]: c["area"] for c in cargos}
    assert areas["TI – Banco de Dados"] == "TI"
    assert areas["Contabilidade"] == "CONTROLE_FISCAL"
    assert all(a is not None and a != "OUTRAS" for a in areas.values())
    assert (tjpb["abrangencia"], tjpb["uf"], tjpb["municipio_ibge"], tjpb["unificado"]) == (
        "ESTADUAL",
        "PB",
        None,
        False,
    )
    # Fase 4: slug estável, campos desnormalizados, resumo e publicação só se for oportunidade.
    assert tjpb["slug"] == "tribunal-de-justica-do-estado-da-paraiba-2026"
    assert (tjpb["total_vagas"], tjpb["salario_max"], tjpb["escolaridades"]) == (50, Decimal("7526.14"), ["SUPERIOR"])
    assert set(tjpb["areas"]) == {"JURIDICA", "TI", "CONTROLE_FISCAL"}
    assert tjpb["resumo"].startswith("Tribunal de Justiça do Estado da Paraíba (PB) ")
    assert "50 vagas" in tjpb["resumo"] and "Banca: FGV." in tjpb["resumo"]
    assert tjpb["publicado"] is (tjpb["situacao"] == "INSCRICOES_ABERTAS")

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
    assert next(r for r in resumos if r.etapa == "RESUMO").itens_novos == 0  # nada mudou: nada regravado
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


def _bloco_realizados(itens: list[tuple[str, str]]) -> str:
    linhas = "".join(f'<div class="views-row"><a href="{href}">{titulo}</a></div>' for href, titulo in itens)
    return f'<div class="view view-concursos-realizados"><div class="view-content">{linhas}</div></div>'


def _pagina_simples(titulo: str, data: date) -> str:
    return f"""<html><body><main><h1>{titulo}</h1>
<div class="field field--name-field-concurso-arquivos"><div class="field__item"><div class="paragraph">
  <time datetime="{data.isoformat()}T12:00:00Z">{data:%d/%m/%Y}</time>
  <a href="{ARQ}/resultado-{data}.pdf">Resultado final</a>
</div></div></div></main></body></html>"""


def test_encerrados_da_fgv_e_classificacao(parametros_coletor, conn_admin, limpar, fixture_texto):
    site = SiteFGVSimulado(fixture_texto)
    conn, orquestrador = criar_orquestrador(parametros_coletor, site)
    consulta = conn_admin.cursor(row_factory=dict_row)
    orquestrador.executar(ETAPAS, fonte="fgv")

    pm = consulta.execute(
        "SELECT abrangencia, uf, situacao FROM concursos.concurso WHERE link_oficial = %s", (PM,)
    ).fetchone()
    assert (pm["abrangencia"], pm["uf"]) == ("ESTADUAL", "PI")
    assert pm["situacao"] != "ENCERRADO"

    # A FGV move o concurso da PM para "realizados" e lista mais dois finalizados que nunca acompanhamos:
    # um recente (entra como encerrado) e um antigo (fora do site: descartado sem criar concurso).
    recente = date.today() - timedelta(days=20)
    linha_pm = (
        '<div class="views-row">\n    <a href="/concursos/teste-pm">'
        "Concurso Público para a Polícia Militar do Estado do Piauí</a></div>"
    )
    assert linha_pm in LISTAGEM
    realizados = _bloco_realizados(
        [
            ("/concursos/teste-pm", "Concurso Público para a Polícia Militar do Estado do Piauí"),
            ("/concursos/teste-recente", "Concurso Público para a Câmara Municipal de Taubaté"),
            ("/concursos/teste-antigo", "Concurso Público para o Tribunal Regional do Trabalho - 16ª Região"),
        ]
    )
    site.paginas["/concursos"] = LISTAGEM.replace(linha_pm, "").replace("</main>", realizados + "</main>")
    site.paginas["/concursos/teste-recente"] = _pagina_simples(
        "Concurso Público para a Câmara Municipal de Taubaté", recente
    )
    site.paginas["/concursos/teste-antigo"] = _pagina_simples(
        "Concurso Público para o Tribunal Regional do Trabalho - 16ª Região", date(2022, 5, 10)
    )
    resumos = orquestrador.executar(ETAPAS, fonte="fgv")
    assert codigo_de_saida(resumos) == 0, resumos

    pm = consulta.execute(
        "SELECT situacao, encerrado_em::date AS desde FROM concursos.concurso WHERE link_oficial = %s", (PM,)
    ).fetchone()
    assert (pm["situacao"], str(pm["desde"])) == ("ENCERRADO", "2026-10-01")  # data da última publicação

    taubate = consulta.execute(
        """SELECT situacao, encerrado_em::date AS desde, abrangencia, uf, municipio_ibge
           FROM concursos.concurso WHERE link_oficial = %s""",
        (RECENTE,),
    ).fetchone()
    assert (taubate["situacao"], taubate["desde"]) == ("ENCERRADO", recente)
    assert (taubate["abrangencia"], taubate["uf"], taubate["municipio_ibge"]) == ("MUNICIPAL", "SP", 3554102)

    assert consulta.execute("SELECT 1 FROM concursos.concurso WHERE link_oficial = %s", (ANTIGO,)).fetchone() is None
    descartado = consulta.execute("SELECT status FROM concursos.sinal_descoberta WHERE url = %s", (ANTIGO,)).fetchone()
    assert descartado["status"] == "DESCARTADO"

    # Documentos de concurso encerrado não são baixados.
    assert not [u for u in site.pdfs_baixados if "resultado-" in u]

    # A PM volta a "em andamento": o concurso é reaberto.
    site.paginas["/concursos"] = LISTAGEM
    orquestrador.executar(("descobrir", "vincular"), fonte="fgv")
    pm = consulta.execute(
        "SELECT situacao, encerrado_em FROM concursos.concurso WHERE link_oficial = %s", (PM,)
    ).fetchone()
    assert (pm["situacao"], pm["encerrado_em"]) == ("EM_ANDAMENTO", None)
    conn.close()


def test_concurso_sem_oportunidade_nao_tem_a_pagina_relida(parametros_coletor, conn_admin, limpar, fixture_texto):
    site = SiteFGVSimulado(fixture_texto)
    conn, orquestrador = criar_orquestrador(parametros_coletor, site)
    orquestrador.executar(ETAPAS, fonte="fgv")

    def relidas() -> set[str]:
        site.paginas_lidas.clear()
        resumos = orquestrador.executar(("descobrir",), fonte="fgv")
        assert codigo_de_saida(resumos) == 0, resumos
        return set(site.paginas_lidas)

    # Inscrições da PM encerradas há 30 dias (além da folga para prorrogação) e sem isenção em curso.
    conn_admin.execute(
        """UPDATE concursos.concurso SET situacao = 'EM_ANDAMENTO', inscricao_fim = current_date - 30
           WHERE link_oficial = %s""",
        (PM,),
    )
    paginas = relidas()
    assert "/concursos/teste-pm" not in paginas
    assert "/concursos/tjpb26" in paginas

    # Encerrada há poucos dias: ainda pode sair prorrogação, então continua acompanhada.
    conn_admin.execute("UPDATE concursos.concurso SET inscricao_fim = current_date - 3 WHERE link_oficial = %s", (PM,))
    assert "/concursos/teste-pm" in relidas()

    # Prazo de isenção em curso também é oportunidade.
    conn_admin.execute(
        """UPDATE concursos.concurso SET inscricao_fim = current_date - 30, tem_isencao = true,
                  isencao_inicio = current_date - 1, isencao_fim = current_date + 5
           WHERE link_oficial = %s""",
        (PM,),
    )
    assert "/concursos/teste-pm" in relidas()

    # Sem oportunidade, mas lida pela última vez há 8 dias: releitura semanal (pega reabertura tardia).
    conn_admin.execute(
        """UPDATE concursos.concurso SET tem_isencao = false, isencao_inicio = NULL, isencao_fim = NULL
           WHERE link_oficial = %s""",
        (PM,),
    )
    assert "/concursos/teste-pm" not in relidas()
    conn_admin.execute(
        "UPDATE concursos.sinal_descoberta SET visto_em = now() - interval '8 days' WHERE url = %s", (PM,)
    )
    assert "/concursos/teste-pm" in relidas()

    # PDF novo de concurso sem oportunidade não é baixado.
    conn_admin.execute(
        """INSERT INTO concursos.documento (concurso_id, tipo, titulo, url_origem)
           SELECT id, 'RETIFICACAO', 'Retificação tardia', %s FROM concursos.concurso WHERE link_oficial = %s""",
        (f"{ARQ}/teste-pm-ret-tardia.pdf", PM),
    )
    orquestrador.executar(("documentos",), fonte="fgv")
    status = conn_admin.execute(
        "SELECT status_extracao FROM concursos.documento WHERE url_origem = %s", (f"{ARQ}/teste-pm-ret-tardia.pdf",)
    ).fetchone()
    assert status == ("IGNORADO",)
    conn.close()


def test_edital_tjpb_grava_isencoes_calendario_e_disciplinas(parametros_coletor, conn_admin, limpar, fixture_texto):
    site = SiteFGVSimulado(fixture_texto)
    conn, orquestrador = criar_orquestrador(parametros_coletor, site)
    orquestrador.executar(ETAPAS, fonte="fgv")
    consulta = conn_admin.cursor(row_factory=dict_row)
    tjpb = consulta.execute(
        "SELECT id, edital_documento_id FROM concursos.concurso WHERE link_oficial = %s", (TJPB,)
    ).fetchone()

    # Grava o edital real (o PDF da simulação é um recorte) como coletor_app: permissões e restrições valem.
    edital = ExtratorFGV().extrair(fixture_texto("fgv/edital_tjpb26_1.txt"))
    repo = Repositorio(conn)
    repo.aplicar_edital(tjpb["id"], tjpb["edital_documento_id"], edital, "INSCRICOES_ABERTAS")
    repo.aplicar_edital(tjpb["id"], tjpb["edital_documento_id"], edital, "INSCRICOES_ABERTAS")  # idempotente

    concurso = consulta.execute(
        "SELECT tem_isencao, isencao_inicio, isencao_fim FROM concursos.concurso WHERE id = %s", (tjpb["id"],)
    ).fetchone()
    assert concurso == {"tem_isencao": True, "isencao_inicio": date(2026, 10, 20), "isencao_fim": date(2026, 10, 27)}
    tipos = consulta.execute(
        "SELECT tipo_codigo, observacao FROM concursos.concurso_isencao WHERE concurso_id = %s", (tjpb["id"],)
    ).fetchall()
    assert {t["tipo_codigo"] for t in tipos} == {i.codigo for i in edital.isencoes}
    eventos = consulta.execute(
        "SELECT ordem, evento, inicio, fim FROM concursos.concurso_evento WHERE concurso_id = %s ORDER BY ordem",
        (tjpb["id"],),
    ).fetchall()
    assert [e["evento"] for e in eventos] == ["Pedido de isenção da taxa", "Inscrições", "Prova objetiva"]
    judiciaria = consulta.execute(
        """SELECT disciplinas, tem_redacao FROM concursos.cargo
           WHERE concurso_id = %s AND especialidade = 'Judiciária'""",
        (tjpb["id"],),
    ).fetchone()
    assert judiciaria["tem_redacao"] is True
    assert judiciaria["disciplinas"][0] == "Língua Portuguesa"
    conn.close()


def test_catalogo_isencoes_igual_ao_banco(conn_admin):
    """config/isencoes.yml é a fonte dos textos; a migration V11 precisa gravar exatamente o mesmo."""
    arquivo = Path(__file__).resolve().parents[2] / "config" / "isencoes.yml"
    catalogo = yaml.safe_load(arquivo.read_text(encoding="utf-8"))["tipos"]
    linhas = (
        conn_admin.cursor(row_factory=dict_row)
        .execute("SELECT codigo, nome, descricao, base_legal, link_oficial FROM concursos.isencao_tipo")
        .fetchall()
    )
    banco = {linha.pop("codigo"): linha for linha in linhas}
    assert set(banco) == set(catalogo)
    for codigo, tipo in catalogo.items():
        esperado = {campo: tipo[campo] for campo in ("nome", "descricao", "base_legal", "link_oficial")}
        assert banco[codigo] == esperado, codigo
        assert tipo["documentos"], codigo
        assert "você tem direito" not in str(tipo).lower(), codigo


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
        "SELECT nome, escolaridade, vagas, area FROM concursos.cargo WHERE concurso_id = %s", (fraiburgo["id"],)
    ).fetchall()
    assert ("Analista de Sistemas", "SUPERIOR", 1, "TI") in [
        (c["nome"], c["escolaridade"], c["vagas"], c["area"]) for c in cargos
    ]
    assert all(c["area"] is not None for c in cargos)
    assert (fraiburgo["abrangencia"], fraiburgo["municipio_ibge"]) == ("MUNICIPAL", 4205506)

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
