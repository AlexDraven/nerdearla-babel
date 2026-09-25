import re

# ASCII imprimible + Latin-1 Supplement (á é í ó ú ü ñ ¿ ¡ y demás letras
# acentuadas) + Latin Extended-A (cobertura extra para algún nombre propio) +
# puntuación tipográfica común (comillas curvas, guiones largos, elipsis).
_ALLOWED_CHARS_RE = re.compile(
    r"[^\t\n\r\x20-\x7E\xA0-\xFFĀ-ſ‘’“”–—…]"
)


def strip_non_latin_chars(text: str) -> str:
    """Filtro determinístico además de la regla del prompt que pide usar solo
    caracteres de español/inglés (app/inference/prompts.py): un modelo
    multimodal chico a veces mete caracteres de otro alfabeto/escritura
    (cirílico, tailandés, chino, etc.) en medio de una oración, incluso con
    la instrucción explícita de no hacerlo. No podemos confiar 100% en que el
    modelo respete esa regla, así que sacamos cualquier carácter fuera del
    rango esperado ANTES de que el texto le llegue a un viewer."""
    return _ALLOWED_CHARS_RE.sub("", text)
