import hashlib
from pathlib import Path

import httpx
import pytest

from coletor.http_cliente import AcessoNaoPermitido, ClienteHttp, ErroHttp, RespostaRecusada

ROBOTS = "User-agent: *\nDisallow: /privado/\n"
PDF = b"%PDF-1.4\n" + b"x" * 2000


class Relogio:
    def __init__(self) -> None:
        self.agora = 0.0
        self.esperas: list[float] = []

    def __call__(self) -> float:
        return self.agora

    def dormir(self, segundos: float) -> None:
        self.esperas.append(round(segundos, 3))
        self.agora += segundos


def criar_cliente(responder, relogio: Relogio | None = None, **kwargs) -> ClienteHttp:
    relogio = relogio or Relogio()

    def com_robots(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        return responder(request)

    return ClienteHttp(
        frozenset({"exemplo.gov.br"}),
        "NqnTech-teste",
        transport=httpx.MockTransport(com_robots),
        relogio=relogio,
        dormir=relogio.dormir,
        **kwargs,
    )


def test_envia_user_agent_identificado():
    vistos = []

    def responder(request):
        vistos.append(request.headers["User-Agent"])
        return httpx.Response(200, text="ok")

    assert criar_cliente(responder).obter_texto("https://exemplo.gov.br/a") == "ok"
    assert vistos == ["NqnTech-teste"]


@pytest.mark.parametrize(
    "url",
    [
        "http://exemplo.gov.br/a",
        "https://outro.com.br/a",
        "https://exemplo.gov.br.malicioso.com/a",
        "https://exemplo.gov.br/privado/x",
    ],
)
def test_bloqueia_fora_da_politica(url):
    with pytest.raises(AcessoNaoPermitido):
        criar_cliente(lambda r: httpx.Response(200)).obter_texto(url)


def test_subdominio_do_dominio_permitido_e_aceito():
    assert criar_cliente(lambda r: httpx.Response(200, text="ok")).obter_texto("https://www.exemplo.gov.br/a") == "ok"


def test_redirecionamento_para_fora_e_bloqueado():
    def responder(request):
        return httpx.Response(302, headers={"Location": "https://golpe.com/pdf"})

    with pytest.raises(AcessoNaoPermitido, match=r"golpe\.com"):
        criar_cliente(responder).obter_texto("https://exemplo.gov.br/a")


def test_robots_com_erro_de_servidor_bloqueia_tudo():
    def responder(request):
        return httpx.Response(503 if request.url.path == "/robots.txt" else 200, text="ok")

    cliente = ClienteHttp(
        frozenset({"exemplo.gov.br"}), "t", transport=httpx.MockTransport(responder), max_tentativas=1, intervalo_s=0
    )
    with pytest.raises(AcessoNaoPermitido, match="robots"):
        cliente.obter_texto("https://exemplo.gov.br/a")


def test_robots_inexistente_libera():
    cliente = ClienteHttp(
        frozenset({"exemplo.gov.br"}),
        "t",
        intervalo_s=0,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(404) if r.url.path == "/robots.txt" else httpx.Response(200, text="ok")
        ),
    )
    assert cliente.obter_texto("https://exemplo.gov.br/a") == "ok"


def test_respeita_intervalo_minimo_por_dominio():
    relogio = Relogio()
    cliente = criar_cliente(lambda r: httpx.Response(200, text="ok"), relogio, intervalo_s=2.5)
    cliente.obter_texto("https://exemplo.gov.br/a")
    cliente.obter_texto("https://exemplo.gov.br/b")
    # robots.txt → /a → /b: duas esperas de 2,5 s
    assert relogio.esperas == [2.5, 2.5]


def test_retenta_erro_temporario_com_espera_crescente():
    tentativas = []

    def responder(request):
        tentativas.append(1)
        return httpx.Response(503) if len(tentativas) < 3 else httpx.Response(200, text="ok")

    relogio = Relogio()
    assert criar_cliente(responder, relogio, intervalo_s=0).obter_texto("https://exemplo.gov.br/a") == "ok"
    assert relogio.esperas == [2.0, 4.0]


def test_nao_retenta_403():
    tentativas = []

    def responder(request):
        tentativas.append(1)
        return httpx.Response(403)

    with pytest.raises(RespostaRecusada, match="403"):
        criar_cliente(responder, intervalo_s=0).obter_texto("https://exemplo.gov.br/a")
    assert len(tentativas) == 1


def test_falha_de_rede_persistente():
    def responder(request):
        raise httpx.ConnectError("sem rota")

    with pytest.raises(ErroHttp, match="persistente"):
        criar_cliente(responder, intervalo_s=0).obter_texto("https://exemplo.gov.br/a")


def test_html_maior_que_o_limite():
    with pytest.raises(RespostaRecusada, match="maior"):
        criar_cliente(lambda r: httpx.Response(200, content=b"a" * 5000), max_bytes_html=1000).obter_texto(
            "https://exemplo.gov.br/a"
        )


def test_baixa_pdf_com_hash(tmp_path: Path):
    cliente = criar_cliente(lambda r: httpx.Response(200, content=PDF, headers={"Content-Type": "application/pdf"}))
    download = cliente.baixar_pdf("https://exemplo.gov.br/edital.pdf", tmp_path, max_bytes=10_000)

    assert download.sha256 == hashlib.sha256(PDF).hexdigest()
    assert download.tamanho == len(PDF)
    assert download.caminho.read_bytes() == PDF


@pytest.mark.parametrize(
    ("conteudo", "cabecalhos", "erro"),
    [
        (b"<html>", {"Content-Type": "text/html"}, "não é PDF"),
        (b"<html>", {"Content-Type": "application/pdf"}, "%PDF-"),
        (PDF, {"Content-Type": "application/pdf", "Content-Length": "999999"}, "excede"),
        (PDF * 10, {"Content-Type": "application/pdf"}, "excede"),
    ],
)
def test_pdf_recusado(tmp_path, conteudo, cabecalhos, erro):
    cliente = criar_cliente(lambda r: httpx.Response(200, content=conteudo, headers=cabecalhos))
    with pytest.raises(RespostaRecusada, match=erro):
        cliente.baixar_pdf("https://exemplo.gov.br/edital.pdf", tmp_path, max_bytes=10_000)
