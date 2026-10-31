"""Testes unitários para o ExtratorConsulpam."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from coletor.extratores.consulpam import ExtratorConsulpam


def test_extrair_edital_consulpam_completo():
    html_exemplo = """
    <html>
        <body>
            <h1>PREFEITURA MUNICIPAL DE SÃO JOÃO DO PIAUÍ-PI</h1>
            <h2>EDITAL Nº 003/2026 - CARGOS GERAIS</h2>
            <div class="conteudo">
                <p>As inscrições estarão abertas no período de 21 DE OUTUBRO A 09 DE NOVEMBRO DE 2026.</p>
                <p>A prova objetiva será realizada na data de 15 de dezembro de 2026.</p>
                <p>O valor da taxa de inscrição é de R$ 80,00 para nível médio e R$ 120,00 para nível superior.</p>
                <p>Isenção do pagamento da taxa de inscrição para inscritos no CadÚnico.</p>
                <h3>DOS CARGOS</h3>
                <ul>
                    <li>Cargo: Agente de Trânsito</li>
                    <li>Cargo: Enfermeiro</li>
                </ul>
            </div>
        </body>
    </html>
    """

    edital = ExtratorConsulpam().extrair(html_exemplo)

    assert edital.numero_edital == "03/2026"
    assert edital.ano == 2026
    assert edital.orgao == "Prefeitura Municipal de São João do Piauí-PI"
    assert edital.inscricao_inicio == date(2026, 10, 21)
    assert edital.inscricao_fim == date(2026, 11, 9)
    assert edital.data_prova == date(2026, 12, 15)
    assert edital.taxa_min == Decimal("80.00")
    assert edital.taxa_max == Decimal("120.00")
    assert "CADUNICO" in edital.isencoes
    assert len(edital.cargos) == 2
    assert edital.cargos[0].nome == "Agente de Trânsito"
    assert edital.cargos[1].nome == "Enfermeiro"


def test_extrator_consulpam_texto_vazio_gerando_avisos():
    edital = ExtratorConsulpam().extrair("")

    assert edital.cargos == ()
    assert edital.numero_edital is None
    assert edital.orgao is None
    assert len(edital.avisos) >= 4
    assert "número do edital não encontrado" in edital.avisos
    assert "órgão não encontrado" in edital.avisos
    assert "período de inscrição não encontrado" in edital.avisos


def test_extrator_consulpam_datas_incoerentes():
    html_incoerente = """
    <html>
