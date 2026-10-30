import httpx
import pytest

from coletor.fontes.fgv import FonteFGV, ItemListagem, eh_concurso, parse_concurso, parse_listagem
from coletor.http_cliente import ClienteHttp, ErroHttp

URL_TJPB = "https://conhecimento.fgv.br/concursos/tjpb26"


def test_listagem_pega_so_o_bloco_em_andamento_e_a_ultima_pagina(fixture_texto):
    pagina = parse_listagem(fixture_texto("fgv/listagem_p0.html"))

    assert len(pagina.itens) == 20
    assert pagina.ultima_pagina == 6
    urls = [i.url for i in pagina.itens]
    assert URL_TJPB in urls
    assert "https://conhecimento.fgv.br/concursos/csjt23" not in urls  # bloco "realizados"


def test_filtra_exames_residencias_e_vestibulares(fixture_texto):
    itens = parse_listagem(fixture_texto("fgv/listagem_p0.html")).itens
    ignorados = {i.titulo for i in itens if not eh_concurso(i)}

    assert len(ignorados) == 6
    assert any("Residência" in t for t in ignorados)
    assert eh_concurso(
        ItemListagem(
            "Concurso Público para Indústrias Nucleares do Brasil S.A. - INB",
            "https://conhecimento.fgv.br/processoseletivo/inb2026",
        )
    )
    assert not eh_concurso(
        ItemListagem("Conselho Federal de Contabilidade", "https://conhecimento.fgv.br/exames/cfc/2026.3")
    )


def test_listagem_sem_bloco_esperado_falha_alto():
    with pytest.raises(ErroHttp, match="layout"):
        parse_listagem("<html><body><p>manutenção</p></body></html>")


def test_pagina_do_concurso_tjpb(fixture_texto):
    dados = parse_concurso(fixture_texto("fgv/concurso_tjpb26.html"), URL_TJPB)

    assert dados["titulo"] == "Concurso Público para Tribunal de Justiça do Estado da Paraíba"
    assert dados["situacao_site"] == "Em Andamento"
    assert "Área de TI" in dados["descricao"]
    assert dados["link_inscricao"] == "https://portal.conhecimento.fgv.br/Concurso/Inscricao"
    assert [a["titulo"] for a in dados["arquivos"]] == [
        "1ª Retificação",
        "Inscrição",
        "Edital (retificado em 26/10/2026)",
    ]
    assert dados["arquivos"][0] == {
        "titulo": "1ª Retificação",
        "url": "https://conhecimento.fgv.br/sites/default/files/concursos/extrato-1a-retificacao-do-edital-tjpb.pdf",
        "data": "2026-10-26",
    }


def test_pagina_sem_arquivos_ainda(fixture_texto):
    dados = parse_concurso(
        fixture_texto("fgv/concurso_prefeiturademacae24.html"),
        "https://conhecimento.fgv.br/concursos/prefeiturademacae24",
    )
    assert dados["arquivos"] == []
    assert dados["titulo"] == "Concurso Público para a Prefeitura de Macaé"


def test_descobrir_percorre_paginas_e_tolera_falha_pontual(fixture_texto):
    paginas = {
        "/robots.txt": fixture_texto("fgv/robots.txt"),
        "/concursos": fixture_texto("fgv/listagem_p0.html"),
        "/concursos?page=1": fixture_texto("fgv/listagem_p1.html"),
        "/concursos/tjpb26": fixture_texto("fgv/concurso_tjpb26.html"),
    }

    def responder(request: httpx.Request) -> httpx.Response:
        chave = request.url.path + (f"?{request.url.query.decode()}" if request.url.query else "")
        if chave in paginas:
            return httpx.Response(200, text=paginas[chave], headers={"Content-Type": "text/html; charset=utf-8"})
        if request.url.path == "/concursos/psabdi":
            return httpx.Response(404)
        return httpx.Response(200, text=fixture_texto("fgv/concurso_prefeiturademacae24.html"))

    http = ClienteHttp(
        frozenset({"conhecimento.fgv.br"}),
        "teste",
        intervalo_s=0,
        transport=httpx.MockTransport(responder),
        dormir=lambda _: None,
    )
    resultado = FonteFGV(max_paginas=2).descobrir(http)  # páginas 0 e 1

    urls = {s.url for s in resultado.sinais}
    assert URL_TJPB in urls
    assert "https://conhecimento.fgv.br/concursos/pcpr26" in urls  # veio da página 2
    assert len(resultado.falhas) == 1 and "psabdi" in resultado.falhas[0]
    tjpb = next(s for s in resultado.sinais if s.url == URL_TJPB)
    assert str(tjpb.data_publicacao) == "2026-10-26"


def test_bloco_realizados_marca_encerrados(fixture_texto):
    pagina = parse_listagem(fixture_texto("fgv/listagem_p0.html"))

    assert len(pagina.realizados.itens) == 20
    assert pagina.realizados.ultima_pagina == 13
    assert all(i.encerrado for i in pagina.realizados.itens)
    assert not any(i.encerrado for i in pagina.andamento.itens)
    assert "https://conhecimento.fgv.br/concursos/csjt23" in {i.url for i in pagina.realizados.itens}


def test_cnu_aparece_na_listagem_e_tem_pagina_propria(fixture_texto):
    itens = parse_listagem(fixture_texto("fgv/listagem_p0.html")).andamento.itens
    cnu = next(i for i in itens if i.url == "https://conhecimento.fgv.br/cpnu2")
    assert eh_concurso(cnu)

    dados = parse_concurso(fixture_texto("fgv/concurso_cpnu2.html"), cnu.url)
    assert dados["titulo"] == "Concurso Público Nacional Unificado 2"
    assert dados["encerrado"] is False
    assert len(dados["arquivos"]) > 100


def _http_simulado(paginas: dict[str, str], padrao: str) -> ClienteHttp:
    def responder(request: httpx.Request) -> httpx.Response:
        chave = request.url.path + (f"?{request.url.query.decode()}" if request.url.query else "")
        return httpx.Response(
            200, text=paginas.get(chave, padrao), headers={"Content-Type": "text/html; charset=utf-8"}
        )

    return ClienteHttp(
        frozenset({"conhecimento.fgv.br"}),
        "teste",
        intervalo_s=0,
        transport=httpx.MockTransport(responder),
        dormir=lambda _: None,
    )


def test_descobrir_le_os_realizados_ate_o_limite(fixture_texto):
    paginas = {
        "/robots.txt": fixture_texto("fgv/robots.txt"),
        "/concursos": fixture_texto("fgv/listagem_p0.html"),
        "/concursos?page=1": fixture_texto("fgv/listagem_p1.html"),
        "/concursos?page=2": fixture_texto("fgv/listagem_p2.html"),
    }
    http = _http_simulado(paginas, fixture_texto("fgv/concurso_prefeiturademacae24.html"))

    # Só "em andamento" na 1ª página, mas "realizados" em duas: a página 1 é lida só pelo bloco realizados.
    resultado = FonteFGV(max_paginas=1, max_paginas_realizados=2).descobrir(http)

    encerrados = {s.url for s in resultado.sinais if s.payload["encerrado"]}
    andamento = {s.url for s in resultado.sinais if not s.payload["encerrado"]}
    assert "https://conhecimento.fgv.br/concursos/csjt23" in encerrados  # realizados, página 0
    assert "https://conhecimento.fgv.br/concursos/trt13" in encerrados  # realizados, página 1
    assert "https://conhecimento.fgv.br/concursos/pcpr26" not in andamento  # andamento, página 1: fora do limite
    assert URL_TJPB in andamento
    # Visto nos dois blocos (listagem mudou durante a leitura): fica "em andamento".
    assert not encerrados & andamento


def test_realizados_desligado(fixture_texto):
    paginas = {"/robots.txt": fixture_texto("fgv/robots.txt"), "/concursos": fixture_texto("fgv/listagem_p0.html")}
    http = _http_simulado(paginas, fixture_texto("fgv/concurso_prefeiturademacae24.html"))

    resultado = FonteFGV(max_paginas=1, max_paginas_realizados=0).descobrir(http)

    assert resultado.sinais and not any(s.payload["encerrado"] for s in resultado.sinais)
