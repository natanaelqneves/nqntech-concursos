"""Fluxo único (sem banco): pré-cadastro pela busca, deduplicação, procura do edital, conferência com o edital,
regra de publicação, cliente HTTP sem lista de domínios, código do Drive e e-mail de pendências."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from coletor.extratores.base import CargoExtraido, EditalExtraido, IsencaoPrevista
from coletor.fontes.busca_ia import AVISO_BUSCA, AgendaBusca, FonteBuscaIA, aceitar, sinal_da_sugestao
from coletor.http_cliente import QUALQUER_DOMINIO_PUBLICO, AcessoNaoPermitido, ClienteHttp, host_publico
from coletor.ia.busca_web import AlvoBusca, RespostaBusca, Sugestao
from coletor.importacao_manual import codigo_do_concurso, codigo_no_nome, tipo_do_anexo
from coletor.pendencias import montar_email
from coletor.pipeline.deduplicacao import Candidato, chave_orgao, procurar_equivalente
from coletor.pipeline.localizacao import escolher_edital, links_de_pdf
from coletor.precadastro import completar_com_busca
from coletor.resumo.gerador import pode_publicar

HOJE = date(2026, 11, 4)


def sugestao(**campos) -> Sugestao:
    base = dict(
        alvo="fcc", orgao="Tribunal Regional do Trabalho da 4ª Região", banca="FCC", esfera="FEDERAL", uf="RS",
        municipio=None, situacao="ABERTO", ano=2026, inscricoes_inicio=date(2026, 11, 1),
        inscricoes_fim=date(2026, 11, 30), isencao_inicio=None, isencao_fim=None, data_prova=date(2027, 2, 15),
        taxa_max=Decimal("120.00"), vagas=30, salario_max=Decimal("16035.69"), cargos=("Analista Judiciário",),
        escolaridades=("SUPERIOR",), link_pagina="https://www.concursosfcc.com.br/trt4",
        link_edital="https://www.concursosfcc.com.br/trt4/edital.pdf", oficial=True, confirmado=True,
    )  # fmt: skip
    base.update(campos)
    return Sugestao(**base)


# --- pré-cadastro -----------------------------------------------------------------------------------------------


def test_sugestao_so_entra_confirmada_oficial_e_ainda_aberta():
    assert aceitar(sugestao(), HOJE) is None
    assert "fontes da busca" in aceitar(sugestao(confirmado=False), HOJE)
    assert "não é da banca" in aceitar(sugestao(oficial=False), HOJE)
    assert aceitar(sugestao(inscricoes_fim=date(2026, 10, 1)), HOJE) == "inscrições já encerradas"
    assert aceitar(sugestao(inscricoes_fim=date(2026, 10, 1), isencao_fim=date(2026, 11, 10)), HOJE) is None


def test_sinal_da_sugestao_leva_os_dados_e_o_edital():
    sinal = sinal_da_sugestao(sugestao(), HOJE, ("concursosfcc.com.br",))
    assert sinal.url == "https://www.concursosfcc.com.br/trt4" and sinal.titulo.endswith("2026")
    (arquivo,) = sinal.payload["arquivos"]
    assert (arquivo["tipo"], arquivo["oficial"]) == ("EDITAL", True)
    dados = sinal.estruturado
    assert dados is not None and dados.situacao == "INSCRICOES_ABERTAS"
    assert dados.uf is None  # órgão federal: a UF da sugestão não vira local do órgão (TRT-4 é tratado pela regra)
    assert dados.cargos == (CargoExtraido("Analista Judiciário", escolaridade="SUPERIOR",
                                          salario=Decimal("16035.69")),)  # fmt: skip
    assert dados.avisos == (AVISO_BUSCA,)
    assert sinal.payload["busca"]["link_edital"].endswith("edital.pdf")
    previsto = sinal_da_sugestao(sugestao(situacao="PREVISTO", esfera="MUNICIPAL", municipio="Sapé"), HOJE)
    assert previsto.payload["arquivos"] == [] and previsto.estruturado.situacao == "PREVISTO"
    assert previsto.estruturado.municipio == "Sapé"
    de_blog = sinal_da_sugestao(sugestao(link_edital="https://blog.com/edital.pdf"), HOJE, ("concursosfcc.com.br",))
    assert de_blog.payload["arquivos"][0]["oficial"] is False


class BuscadorFixo:
    nome = "fixo"

    def __init__(self, texto: str) -> None:
        self.texto = texto
        self.pedidos: list[str] = []

    def buscar(self, pedido: str) -> RespostaBusca:
        self.pedidos.append(pedido)
        return RespostaBusca(self.texto, {"groundingChunks": [{"web": {"title": "concursosfcc.com.br"}}]})


def test_fonte_busca_so_pesquisa_alvos_vencidos_e_registra():
    texto = """[{"orgao": "TRT 4", "situacao": "ABERTO", "inscricoes_fim": "2026-11-30",
                 "link_pagina": "https://www.concursosfcc.com.br/trt4"},
                {"orgao": "Blog", "link_pagina": "https://blog.com/x"}]"""
    buscador = BuscadorFixo(texto)
    registrados = []
    alvos = [AlvoBusca("fcc", "FCC", "FCC", ("concursosfcc.com.br",)), AlvoBusca("sul", "Sul")]
    fechado = []
    fonte = FonteBuscaIA(
        lambda: ([buscador], lambda: fechado.append(True)),
        alvos,
        AgendaBusca(lambda codigos: [c for c in codigos if c == "fcc"], registrados.append),
        lambda: HOJE,
        max_alvos=5,
    )
    resultado = fonte.descobrir(None)  # type: ignore[arg-type]  # não acessa sites
    assert len(buscador.pedidos) == 1 and "FCC" in buscador.pedidos[0]
    assert [s.url for s in resultado.sinais] == ["https://www.concursosfcc.com.br/trt4"]
    assert [r.alvo.codigo for r in registrados] == ["fcc"] and fechado == [True]


# --- deduplicação -----------------------------------------------------------------------------------------------


def test_chave_do_orgao_ignora_variacoes():
    assert chave_orgao("Prefeitura Municipal de Sapé") == chave_orgao("PREFEITURA DE SAPÉ")
    assert chave_orgao("Câmara Municipal de Patos") != chave_orgao("Prefeitura de Patos")


def test_equivalente_conservador():
    candidatos = [
        Candidato(1, "Prefeitura de Sapé", "PB", None, 2026, True),
        Candidato(2, "Prefeitura de Patos", "PB", 7, 2026, False),
        Candidato(3, "Prefeitura de Patos", "PB", 7, 2026, False),
        Candidato(4, "TJ", None, None, None, False),
    ]
    assert procurar_equivalente("Prefeitura Municipal de Sapé", "PB", 5, 2026, candidatos).concurso_id == 1
    assert procurar_equivalente("Prefeitura de Sapé", "PE", None, 2026, candidatos).concurso_id is None
    ambiguo = procurar_equivalente("Prefeitura de Patos", "PB", None, None, candidatos)
    assert (ambiguo.concurso_id, ambiguo.ambiguo) == (None, True)
    assert procurar_equivalente("TJ", None, None, None, candidatos).concurso_id is None  # nome curto demais
    so_busca = procurar_equivalente("Prefeitura de Patos", "PB", 7, 2026, candidatos, somente_busca=True)
    assert (so_busca.concurso_id, so_busca.ambiguo) == (None, False)


# --- procura do edital ------------------------------------------------------------------------------------------

PAGINA = """<html><body>
<a href="/arquivos/resultado-final.pdf">Resultado final</a>
<a href="/arquivos/edital-retificacao-1.pdf">Edital de retificação nº 1</a>
<a href="http://inseguro.com/edital.pdf">Edital</a>
<a href="/arquivos/ed01.pdf">Edital nº 01/2026 - Abertura</a>
<a href="docs/manual.pdf">Manual do candidato</a>
</body></html>"""


def test_escolhe_o_edital_de_abertura_entre_os_pdfs_da_pagina():
    links = links_de_pdf(PAGINA, "https://banca.org.br/concurso/x")
    assert links[0][1] == "https://banca.org.br/arquivos/resultado-final.pdf"
    assert all(u.startswith("https://") for _, u in links)
    assert escolher_edital(links) == "https://banca.org.br/arquivos/ed01.pdf"
    assert escolher_edital([("Gabarito", "https://x.org/gab.pdf")]) is None
    assert escolher_edital([("Baixar", "https://x.org/edital-concurso.pdf")]) == "https://x.org/edital-concurso.pdf"


# --- conferência com o edital -----------------------------------------------------------------------------------

BUSCA = {
    "orgao": "Prefeitura de Sapé",
    "esfera": "MUNICIPAL",
    "uf": "PB",
    "inscricoes_inicio": "2026-11-01",
    "inscricoes_fim": "2026-11-30",
    "data_prova": "2027-01-10",
    "taxa_max": "80.00",
    "isencao_fim": "2026-11-08",
    "cargos": ["Professor", "Agente"],
}


def test_edital_vence_e_busca_so_preenche_lacunas():
    edital = EditalExtraido(
        inscricao_fim=date(2026, 12, 2),
        isencoes=(IsencaoPrevista("CADUNICO"),),
        cargos=(CargoExtraido("Professor", vagas=10),),
        avisos=("data da prova não encontrada no edital", "taxa de inscrição não encontrada"),
    )
    final = completar_com_busca(edital, BUSCA, 1)
    assert final.inscricao_fim == date(2026, 12, 2)  # do edital, mesmo divergindo da busca
    assert (final.inscricao_inicio, final.data_prova, final.taxa_max) == (
        date(2026, 11, 1),
        date(2027, 1, 10),
        Decimal("80.00"),
    )
    assert final.isencao_fim == date(2026, 11, 8)
    assert final.cargos == edital.cargos  # o quadro do edital fica
    assert (final.orgao, final.esfera, final.uf) == ("Prefeitura de Sapé", "MUNICIPAL", "PB")
    assert not any(a.startswith(("data da prova não", "taxa de inscrição não")) for a in final.avisos)
    assert any("busca na web" in a and "confira o edital" in a for a in final.avisos)


def test_sem_isencao_no_edital_a_busca_nao_inventa_prazo():
    final = completar_com_busca(EditalExtraido(data_prova=date(2027, 1, 10)), BUSCA)
    assert final.isencao_fim is None and [c.nome for c in final.cargos] == ["Professor", "Agente"]
    assert completar_com_busca(EditalExtraido(), None) == EditalExtraido()


# --- publicação -------------------------------------------------------------------------------------------------


def test_aberto_so_vai_ao_site_com_edital_e_previsto_vai_sem():
    assert pode_publicar("ESTADUAL", "INSCRICOES_ABERTAS", None, True, HOJE)
    assert not pode_publicar("ESTADUAL", "INSCRICOES_ABERTAS", None, False, HOJE)
    assert pode_publicar("MUNICIPAL", "PREVISTO", None, False, HOJE)
    assert not pode_publicar(None, "PREVISTO", None, False, HOJE)
    assert not pode_publicar("NACIONAL", "ENCERRADO", None, True, HOJE)
    assert pode_publicar("NACIONAL", "EM_ANDAMENTO", date(2026, 11, 5), True, HOJE)  # isenção em curso


# --- cliente HTTP em qualquer domínio público --------------------------------------------------------------------


def test_host_publico_bloqueia_rede_interna():
    assert host_publico("editais.exemplo.com.br", lambda h: ["93.184.216.34"])
    assert not host_publico("127.0.0.1", lambda h: ["127.0.0.1"])
    assert not host_publico("intranet", lambda h: ["93.184.216.34"])
    assert not host_publico("servico.local", lambda h: ["93.184.216.34"])
    assert not host_publico("rebind.exemplo.com", lambda h: ["10.0.0.5"])
    assert not host_publico("metadados.exemplo.com", lambda h: ["169.254.169.254"])

    def sem_dns(_):
        raise OSError("sem DNS")

    assert not host_publico("nao-existe.exemplo.com", sem_dns)


def test_cliente_qualquer_dominio_publico(tmp_path: Path):
    pdf = b"%PDF-1.4 teste"

    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=pdf, headers={"Content-Type": "application/pdf"})

    ips = {"blog.exemplo.com": ["93.184.216.34"], "interno.exemplo.com": ["192.168.0.10"]}
    cliente = ClienteHttp(QUALQUER_DOMINIO_PUBLICO, "teste", intervalo_s=0, transport=httpx.MockTransport(responder),
                          resolver=lambda h: ips[h])  # fmt: skip
    with cliente:
        assert cliente.baixar_pdf("https://blog.exemplo.com/e.pdf", tmp_path, 1000).tamanho == len(pdf)
        with pytest.raises(AcessoNaoPermitido):
            cliente.baixar_pdf("https://interno.exemplo.com/e.pdf", tmp_path, 1000)
        with pytest.raises(AcessoNaoPermitido):
            cliente.baixar_pdf("http://blog.exemplo.com/e.pdf", tmp_path, 1000)


# --- código do concurso e pendências ----------------------------------------------------------------------------


def test_codigo_no_nome_do_arquivo():
    assert codigo_do_concurso(123) == "NQ-123"
    assert codigo_no_nome("NQ-123 edital.pdf") == 123
    assert codigo_no_nome("edital_nq_45.pdf") == 45
    assert codigo_no_nome("Edital NQ 7 - abertura.pdf") == 7
    assert codigo_no_nome("ANQ-12.pdf") is None
    assert codigo_no_nome("edital-2026.pdf") is None


def test_tipo_do_anexo_pelo_nome():
    assert tipo_do_anexo("NQ-12 edital.pdf") == "EDITAL"
    assert tipo_do_anexo("NQ-12.pdf") == "EDITAL"
    assert tipo_do_anexo("NQ-12 Edital de Abertura - Anexo I.pdf") == "EDITAL"
    assert tipo_do_anexo("NQ-12 cronograma.pdf") == "OUTRO"
    assert tipo_do_anexo("NQ-12 quadro de vagas.pdf") == "OUTRO"
    assert tipo_do_anexo("NQ-12 Retificação 1.pdf") == "RETIFICACAO"


def test_email_diario_com_as_tres_listas():
    novos = [{"id": 11, "orgao": "IBFC - MGS", "banca": "IBFC", "inscricao_fim": None, "situacao": "PREVISTO",
              "link_oficial": "https://ibfc.org.br/x", "publicado": True}]  # fmt: skip
    aguardando = [
        {"id": 12, "orgao": "Prefeitura de Sapé", "banca": "CPCON", "inscricao_fim": date(2026, 11, 30),
         "link_oficial": "https://cpcon.uepb.edu.br/x", "link_edital": None,
         "edital_falha": "robots.txt não permite"},
        {"id": 13, "orgao": "Câmara de Patos", "banca": None, "inscricao_fim": None,
         "link_oficial": "https://patos.pb.leg.br/c", "link_edital": "https://blog.com/e.pdf", "edital_falha": None},
    ]  # fmt: skip
    faltando = [{"id": 14, "orgao": "TJPB", "banca": "FGV", "inscricao_fim": None, "link_oficial": "https://fgv.br/t",
                 "faltam": ["data da prova", "salário"]}]  # fmt: skip
    assunto, corpo = montar_email(novos, aguardando, faltando, HOJE)
    assert assunto == "NqnTech 04/11/2026: 1 novo(s), 2 aguardando edital, 1 com dados faltando"
    assert "NQ-11 — IBFC - MGS (IBFC) [previsto, no site]" in corpo
    assert "NQ-12 — Prefeitura de Sapé (CPCON) — inscrições até 30/11/2026" in corpo
    assert "Por que não baixou: robots.txt não permite" in corpo
    assert "NQ-13 — Câmara de Patos\n" in corpo and "PDF indicado pela busca: https://blog.com/e.pdf" in corpo
    assert "NQ-14 — TJPB (FGV)\n  Falta: data da prova, salário" in corpo
    assert "== 1." in corpo and "== 3." in corpo
    _, so_faltando = montar_email([], [], faltando, HOJE)
    assert "== 1." not in so_faltando and "== 2." not in so_faltando
