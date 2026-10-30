import httpx

from coletor.fontes.ibade import AVISO_SEM_DETALHES, FonteIBADE, parse_edital, parse_listagem
from coletor.http_cliente import ClienteHttp


def test_listagem_pega_abertos_e_andamento_e_ignora_encerrados(fixture_texto):
    itens = parse_listagem(fixture_texto("ibade/lista.html"))

    assert len(itens) == 9
    assert itens[0] == (
        "https://portal.ibade.selecao.site/edital/ver/128",
        "Processo Seletivo - 31/2026 - SECRETARIA DE SEGURANÇA, DEFESA E CIDADANIA DE RONDÔNIA - SESDEC",
        "INSCRICOES_ABERTAS",
    )
    assert {situacao for _, _, situacao in itens[1:]} == {"EM_ANDAMENTO"}


def test_pagina_do_concurso_com_cargos_e_arquivos(fixture_texto):
    sinal = parse_edital(
        fixture_texto("ibade/edital_129.html"), "https://portal.ibade.selecao.site/edital/ver/129", "EM_ANDAMENTO"
    )
    dados = sinal.estruturado

    assert dados.orgao == "Conselho Regional de Educação Física da 22ª Região – CREF22/ES"
    assert (dados.uf, dados.numero_edital, dados.ano) == ("ES", "01/2026", 2026)
    assert [(c.nome, c.escolaridade) for c in dados.cargos] == [
        ("Advogado I", "SUPERIOR"),
        ("Analista Administrativo I", "SUPERIOR"),
        ("Contador I", "SUPERIOR"),
    ]
    assert dados.avisos == (AVISO_SEM_DETALHES,)
    edital = next(a for a in sinal.payload["arquivos"] if a["titulo"] == "EDITAL DE ABERTURA")
    assert edital["pdf"] is True and edital["data"] == "2026-09-18"
    assert edital["url"].startswith("https://ibade.selecao.site/arquivo.php?file=edital/1/129/")
    assert str(sinal.data_publicacao) == "2026-10-20"


def test_lotacao_sai_do_nome_e_cargos_repetidos_viram_um(fixture_texto):
    dados = parse_edital(fixture_texto("ibade/edital_128.html"), "u", "INSCRICOES_ABERTAS").estruturado
    assert dados.uf == "RO"
    assert [c.nome for c in dados.cargos] == [
        "Prestador Voluntário de Serviços Administrativos (CORPO DE BOMBEIROS MILITAR)",
        "Prestador Voluntário de Serviços Administrativos (POLÍCIA MILITAR)",
    ]


def test_descobrir_segue_as_paginas_e_tolera_falha(fixture_texto):
    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/edital":
            return httpx.Response(200, text=fixture_texto("ibade/lista.html"))
        if request.url.path == "/edital/ver/128":
            return httpx.Response(200, text=fixture_texto("ibade/edital_128.html"))
        return httpx.Response(500)

    http = ClienteHttp(
        frozenset({"portal.ibade.selecao.site"}),
        "t",
        intervalo_s=0,
        max_tentativas=1,
        transport=httpx.MockTransport(responder),
    )
    resultado = FonteIBADE().descobrir(http)

    assert [s.url for s in resultado.sinais] == ["https://portal.ibade.selecao.site/edital/ver/128"]
    assert len(resultado.falhas) == 8


def test_unidade_de_lotacao_nao_vira_cargo():
    from bs4 import BeautifulSoup

    from coletor.fontes.ibade import _cargos

    html = """<div id="vagas"><div class="card"><div class="card-header">Nível Superior</div>
      <div class="list-group-item">
        <p><span>S01 - Professor de Matemática - UN: EMEF Progresso - TIPOLOGIA: D</span></p></div>
      <div class="list-group-item"><p><span>UN: EMEF Rio Verde - TIPOLOGIA: D</span></p></div>
    </div></div>"""
    assert [c.nome for c in _cargos(BeautifulSoup(html, "lxml"))] == ["Professor de Matemática"]
