"""Identidade visual Corte City (v2, "Vice"): uma fonte só para as cores e a marca.

Sistema completo (logo, regras, componentes): artifact "Corte City — Sistema Visual Vice".
Rosa e azul mandam; ciano só em traço fino; laranja/amarelo só no degradê de pôr do sol.
"""
from __future__ import annotations

from .config import RAIZ

NOITE = (10, 14, 42)        # #0A0E2A fundo
OCEANO = (19, 35, 92)       # #13235C cards
AREIA = (255, 243, 227)     # #FFF3E3 texto
NEVOA = (169, 180, 232)     # #A9B4E8 texto secundário
ROSA = (255, 61, 127)       # #FF3D7F cor nº1
AZUL = (31, 184, 255)       # #1FB8FF cor nº2
CIANO = (61, 245, 230)      # #3DF5E6 traço fino
AMEIXA = (91, 18, 64)       # #5B1240 sombra dura
SOL = [(106, 31, 176), (194, 42, 158), (255, 61, 127), (255, 138, 61), (255, 201, 74)]  # degradê de pôr do sol

MONOGRAMA = RAIZ / "assets" / "marca" / "cc.png"      # CC transparente (marca d'água)
ICONE = RAIZ / "assets" / "marca" / "icone.png"


def hexa(c: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % c


def ass(c: tuple[int, int, int], alfa: int = 0) -> str:
    """Cor no formato do ASS (&HAABBGGRR)."""
    return "&H%02X%02X%02X%02X" % (alfa, c[2], c[1], c[0])


def degrade_sol(largura: int, altura: int, cores=None):
    """Imagem PIL vertical com o degradê de pôr do sol."""
    from PIL import Image
    cores = cores or SOL
    img = Image.new("RGB", (1, altura))
    n = len(cores) - 1
    for y in range(altura):
        p = y / max(1, altura - 1) * n
        i = min(int(p), n - 1)
        f = p - i
        a, b = cores[i], cores[i + 1]
        img.putpixel((0, y), tuple(int(a[k] + (b[k] - a[k]) * f) for k in range(3)))
    return img.resize((largura, altura))
