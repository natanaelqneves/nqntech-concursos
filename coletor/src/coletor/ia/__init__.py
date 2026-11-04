"""Camada 2 da extração: IA com saída estruturada (JSON Schema), usada só quando as regras não bastam.

Fluxo (seção 6 do contexto): triagem heurística do PDF → recorte dos trechos úteis → cache pelo SHA-256 do edital
→ provedores em fallback (Gemini, depois Groq), cada um dentro do próprio limite → validação → EditalExtraido.
"""

from coletor.ia.extrator import ExtratorIA, ResultadoIA
from coletor.ia.provedores import ConfigIA, criar_provedores

__all__ = ["ConfigIA", "ExtratorIA", "ResultadoIA", "criar_provedores"]
