"""Thumb automática no estilo que funciona no Brasil:
rosto grande da reação, uma palavra gigante com contorno grosso, seta vermelha e borda na cor do canal."""
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
    """frame_bgr = frame do vídeo original (16:9) no pico da reação."""
    base = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    fundo = ImageOps.fit(base, (TW, TH), Image.LANCZOS)
    fundo = Image.blend(fundo, Image.new("RGB", (TW, TH), (10, 10, 15)), 0.25)

    # rosto grande à esquerda: usa a webcam se achou; senão dá um zoom no centro do frame
    if webcam:
        rosto = base.crop((webcam["x"], webcam["y"], webcam["x"] + webcam["l"], webcam["y"] + webcam["a"]))
    else:
        w, h = base.size
        rosto = base.crop((int(w * 0.2), int(h * 0.1), int(w * 0.65), int(h * 0.9)))
    rosto = ImageOps.fit(rosto, (int(TW * 0.55), TH), Image.LANCZOS)
    sombra = Image.new("L", rosto.size, 0)
    ImageDraw.Draw(sombra).rectangle((0, 0, rosto.size[0] - 30, rosto.size[1]), fill=255)
    sombra = sombra.filter(ImageFilter.GaussianBlur(25))
    fundo.paste(rosto, (0, 0), sombra)

    d = ImageDraw.Draw(fundo)
    gancho = (gancho or "INSANO").upper()
    palavras = gancho.split()
    linhas = [gancho] if len(palavras) == 1 or len(gancho) <= 9 else [" ".join(palavras[:len(palavras) // 2]),
                                                                    " ".join(palavras[len(palavras) // 2:])]
    x0, y = int(TW * 0.5), 60
    for linha in linhas:
        f = _ajustar(linha, TW - x0 - 50, 230 if len(linhas) == 1 else 170)
        _texto_contornado(d, (x0, y), linha, f, _hex(cor) if linha == linhas[0] else (255, 255, 255))
        y += f.getbbox(linha)[3] + 20

    # seta vermelha apontando para o rosto
    ax, ay = int(TW * 0.62), int(TH * 0.72)
    seta = [(ax + 150, ay - 40), (ax + 30, ay - 40), (ax + 30, ay - 90), (ax - 70, ay), (ax + 30, ay + 90),
            (ax + 30, ay + 40), (ax + 150, ay + 40)]
    d.polygon(seta, fill=VERMELHO, outline=(0, 0, 0), width=8)

    if etiqueta:  # ex.: "TOP 10" ou nome do streamer
        f = _fonte(70)
        caixa = d.textbbox((0, 0), etiqueta, font=f)
        lx, ly = TW - (caixa[2] - caixa[0]) - 70, TH - 130
        d.rectangle((lx - 20, ly - 6, TW - 50, ly + 92), fill=VERMELHO)
        d.text((lx, ly), etiqueta, font=f, fill=(255, 255, 255))

    # borda na cor do canal
    d.rectangle((0, 0, TW - 1, TH - 1), outline=_hex(cor), width=16)
    fundo.save(destino, "JPEG", quality=92)
    return destino
