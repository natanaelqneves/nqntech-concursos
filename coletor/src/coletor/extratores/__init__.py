from coletor.extratores.base import CargoExtraido, EditalExtraido, Extrator
from coletor.extratores.cesgranrio import ExtratorCesgranrio
from coletor.extratores.fgv import ExtratorFGV

__all__ = ["CargoExtraido", "EditalExtraido", "Extrator", "ExtratorCesgranrio", "ExtratorFGV", "extrator_para_banca"]


def extrator_para_banca(sigla: str | None) -> Extrator | None:
    return {
        "FGV": ExtratorFGV(),
        "CESGRANRIO": ExtratorCesgranrio(),
    }.get((sigla or "").upper())
