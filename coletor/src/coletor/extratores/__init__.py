from coletor.extratores.base import CargoExtraido, EditalExtraido, Extrator
from coletor.extratores.fgv import ExtratorFGV
from coletor.extratores.cesgranrio import ExtratorCesgranrio

__all__ = ["CargoExtraido", "EditalExtraido", "Extrator", "ExtratorFGV", "ExtratorCesgranrio", "extrator_para_banca"]


def extrator_para_banca(sigla: str | None) -> Extrator | None:
    return {
        "FGV": ExtratorFGV(),
        "CESGRANRIO": ExtratorCesgranrio(),
    }.get((sigla or "").upper())
