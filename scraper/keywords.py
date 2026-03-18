"""Palabras clave y frases semilla para la detección de discurso misógino.

Esta lista debe ampliarse y revisarse periódicamente con criterio experto
en detección de discurso de odio. Los términos incluyen expresiones tanto
en español como en inglés, cubriendo distintos registros y contextos
de misoginia online (insultos directos, cosificación, menosprecio,
estereotipos, etc.).

NOTA: La presencia de un término en esta lista no implica que todo
contenido que lo contenga sea misógino; se usa como filtro inicial
para alimentar el pipeline de análisis.
"""

MISOGYNY_SEED_QUERIES: list[str] = [
    # --- Español ---
    "puta",
    "zorra",
    "calladita te ves más bonita",
    "mujer sumisa",
    "feminazi",
    "las mujeres no saben",
    "vuelve a la cocina",
    "histérica",
    "golfa",
    "mujer tenías que ser",
    "se lo buscó",
    "todas putas",
    "hembrismo",
    "privilegio femenino",
    "debería estar en la cocina",
    "no es para mujeres",
    
    # --- English ---
    "misogyny",
    "women belong in the kitchen",
    "she deserved it",
    "shut up woman",
    "female hysteria",
    "gold digger",
    "make me a sandwich",
    "women are inferior",
    "bossy woman",
    "typical woman",
    "women logic",
    "incel",
    "she asked for it",
    "not all men",
    "feminazi",
]
