from coletor.fontes.base import DadosEstruturados, Fonte, ResultadoDescoberta, SinalDescoberta
from coletor.fontes.fgv import FonteFGV
from coletor.fontes.ibade import FonteIBADE
from coletor.fontes.ibam import FonteIBAM

__all__ = ["DadosEstruturados", "Fonte", "ResultadoDescoberta", "SinalDescoberta", "fontes_disponiveis"]


def fontes_disponiveis(max_paginas_listagem: int = 15, max_paginas_realizados: int = 0) -> dict[str, Fonte]:
    """Adaptadores registrados, pelo nome cadastrado em concursos.fonte (só rodam as fontes ativas no banco)."""
    fontes: list[Fonte] = [
        FonteFGV(max_paginas=max_paginas_listagem, max_paginas_realizados=max_paginas_realizados),
        FonteIBAM(),
        FonteIBADE(),
    ]
    return {fonte.nome: fonte for fonte in fontes}
