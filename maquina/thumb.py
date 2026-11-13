"""Thumb automática na identidade Vice da Corte City (ver maquina/marca.py)."""
from __future__ import annotations

from pathlib import Path

import cv2
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .config import FONTES

TW, TH = 1280, 720
VERMELHO = (255, 59, 78)


def _fonte(tam: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTES / "Anton-Regular.ttf"), tam)


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _texto_contornado(d: ImageDraw.ImageDraw, xy, texto, fonte, cor, contorno=14):
    d.text(xy, texto, font=fonte, fill=cor, stroke_width=contorno, stroke_fill=(0, 0, 0))


def _ajustar(texto: str, largura_max: int, tam_max: int, tam_min: int = 90) -> ImageFont.FreeTypeFont:
    tam = tam_max
    while tam > tam_min:
        f = _fonte(tam)
        if f.getbbox(texto)[2] <= largura_max:
            return f
        tam -= 8
    return _fonte(tam_min)


def gerar_thumb(frame_bgr, destino: Path, gancho: str, cor: str, webcam: dict | None = None,
                etiqueta: str | None = None) -> Path:
    """Thumb Vice: o momento à esquerda cortado por uma diagonal ciano; à direita céu noite→rosa com sol
    listrado e o gancho em Anton (areia com sombra dura ameixa, a última palavra em azul).
    frame_bgr = frame do vídeo original (16:9) no pico da reação."""
    from . import marca as M
    base = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))

    # céu: noite -> ameixa -> rosa -> laranja, com sol listrado na direita
    ceu = M.degrade_sol(TW, TH, [M.NOITE, (42, 18, 96), (138, 31, 142), M.ROSA, (255, 138, 61)])
    sol = M.degrade_sol(380, 380, [(255, 201, 74), (255, 138, 61), M.ROSA])
    masc = Image.new("L", (380, 380), 0)
    dm = ImageDraw.Draw(masc)
    dm.ellipse((0, 0, 379, 379), fill=255)
    for i, y in enumerate(range(120, 380, 30)):
        dm.rectangle((0, y, 380, y + 6 + i * 3), fill=0)
    ceu.paste(sol, (TW - 430, TH - 250), masc)
    fundo = ceu

    # o momento (rosto da webcam, ou zoom no centro) ocupa ~60% à esquerda, cortado na diagonal
    if webcam:
        rosto = base.crop((webcam["x"], webcam["y"], webcam["x"] + webcam["l"], webcam["y"] + webcam["a"]))
    else:
        w, h = base.size
        rosto = base.crop((int(w * 0.15), int(h * 0.05), int(w * 0.75), int(h * 0.95)))
    larg = int(TW * 0.62)
    rosto = ImageOps.fit(rosto, (larg, TH), Image.LANCZOS)
    corte = Image.new("L", (larg, TH), 0)
    ImageDraw.Draw(corte).polygon([(0, 0), (larg, 0), (larg - 150, TH), (0, TH)], fill=255)
    fundo.paste(rosto, (0, 0), corte)
    d = ImageDraw.Draw(fundo)
    d.line([(larg, -10), (larg - 152, TH + 10)], fill=M.CIANO, width=9)

    # gancho: até 3 linhas na direita, a última em azul
    gancho = (gancho or "INSANO").upper()
    palavras = gancho.split()
    if len(palavras) <= 1:
        linhas = [gancho]
    elif len(palavras) <= 3:
        linhas = palavras
    else:
        meio = len(palavras) // 2
        linhas = [" ".join(palavras[:meio]), " ".join(palavras[meio:])]
    area_l = TW - larg + 20
    y = 70
    for i, linha in enumerate(linhas):
        f = _ajustar(linha, area_l, 200 if len(linhas) == 1 else 150, 70)
        larg_txt = f.getbbox(linha)[2]
        x = TW - 40 - larg_txt
        corl = M.AZUL if i == len(linhas) - 1 and len(linhas) > 1 else M.AREIA
        d.text((x + 9, y + 9), linha, font=f, fill=M.AMEIXA)          # sombra dura
        d.text((x, y), linha, font=f, fill=corl, stroke_width=5, stroke_fill=M.NOITE)
        y += f.getbbox(linha)[3] + 14

    # assinatura pequena no canto
    f = _fonte(34)
    d.text((28, 22), "CORTE CITY", font=f, fill=M.ROSA, stroke_width=3, stroke_fill=M.NOITE)

    if etiqueta:  # ex.: "TOP 10" ou nome do streamer: placa azul embaixo à direita
        f = _fonte(64)
        caixa = d.textbbox((0, 0), etiqueta, font=f)
        lx, ly = TW - (caixa[2] - caixa[0]) - 70, TH - 120
        d.rectangle((lx - 22, ly - 4, TW - 48, ly + 84), fill=M.AZUL)
        d.text((lx, ly), etiqueta, font=f, fill=M.NOITE)

    fundo.save(destino, "JPEG", quality=92)
    return destino
