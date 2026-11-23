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


def _thumb_classica(frame_bgr, destino: Path, gancho: str, cor: str, webcam: dict | None = None,
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


# ============================================================================ thumb nova (v2)
# A antiga era um molde: metade da tela um degradê igual em todo vídeo e o rosto esticado e borrado.
# A nova usa o frame do próprio vídeo na tela inteira, recorta o streamer do fundo (IA de recorte, grátis)
# e põe o gancho gigante por cima. Cada thumb sai diferente porque o fundo é o momento de verdade.
AMARELO = (255, 230, 0)
_SESSAO = None


def _sessao():
    """Modelo que separa a pessoa do fundo (rembg). Se não estiver instalado, a thumb sai sem recorte."""
    global _SESSAO
    if _SESSAO is None:
        try:
            import os
            from .config import RAIZ
            os.environ.setdefault("U2NET_HOME", str(RAIZ / ".cache" / "rembg"))
            from rembg import new_session
            _SESSAO = new_session("u2net_human_seg")
        except Exception as e:
            print(f"  aviso: recorte de pessoa indisponível ({str(e)[:80]}), thumb sem recorte")
            _SESSAO = False
    return _SESSAO or None


def _nitidez(img_bgr) -> float:
    cinza = cv2.cvtColor(cv2.resize(img_bgr, (640, 360)), cv2.COLOR_BGR2GRAY)
    luz = float(cinza.mean())
    pena = 0.25 if luz < 45 or luz > 215 else 1.0  # tela preta/branca (loading, transição) não vira capa
    return float(cv2.Laplacian(cinza, cv2.CV_64F).var()) * pena


def melhor_frame(video: Path, centro: float, janela: float = 5.0, passos: int = 11):
    """O frame mais nítido e bem iluminado em volta do pico (o do pico exato costuma sair borrado de movimento)."""
    cap = cv2.VideoCapture(str(video))
    melhor, nota = None, -1.0
    for i in range(passos):
        t = max(0.0, centro - janela + 2 * janela * i / max(1, passos - 1))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, img = cap.read()
        if not ok:
            continue
        n = _nitidez(img)
        if n > nota:
            melhor, nota = img, n
    cap.release()
    return melhor


def _pessoa(base: Image.Image):
    """(recorte RGBA da pessoa, fração da tela que ela ocupa) ou (None, 0)."""
    ses = _sessao()
    if not ses:
        return None, 0.0
    try:
        import numpy as np
        from rembg import remove
        masc = remove(base, session=ses, only_mask=True).convert("L")
        a = np.array(masc) > 128
        if a.mean() < 0.012:
            return None, 0.0
        ys, xs = np.where(a)
        x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
        if y1 - y0 < 150:  # webcam minúscula: ampliar vira borrão, melhor não recortar
            return None, float(a.mean())
        rec = base.convert("RGBA")
        rec.putalpha(masc.filter(ImageFilter.GaussianBlur(1.2)))
        return rec.crop((x0, y0, x1, y1)), float(a.mean())
    except Exception as e:
        print(f"  aviso: recorte falhou ({str(e)[:80]})")
        return None, 0.0


def _linhas(gancho: str) -> list[str]:
    palavras = (gancho or "OLHA ISSO").upper().split()[:5]
    if len(palavras) <= 2:
        return palavras
    meio = (len(palavras) + 1) // 2
    return [" ".join(palavras[:meio]), " ".join(palavras[meio:])]


def gerar_thumb(frame_bgr, destino: Path, gancho: str, cor: str, webcam: dict | None = None,
                etiqueta: str | None = None, video: Path | None = None, pico: float | None = None) -> Path:
    """Thumb v2: frame do vídeo em tela cheia + streamer recortado com contorno + gancho gigante.
    Se der qualquer problema, cai na thumb clássica (nunca derruba o vídeo)."""
    try:
        return _thumb_v2(frame_bgr, destino, gancho, etiqueta, video, pico)
    except Exception as e:
        print(f"  aviso: thumb nova falhou ({str(e)[:100]}), usando a clássica")
        return _thumb_classica(frame_bgr, destino, gancho, cor, webcam, etiqueta)


def _thumb_v2(frame_bgr, destino, gancho, etiqueta, video, pico) -> Path:
    from PIL import ImageEnhance
    from . import marca as M
    if video is not None and pico is not None:
        bom = melhor_frame(Path(video), float(pico))
        if bom is not None:
            frame_bgr = bom
    base = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    if base.width < base.height:  # vídeo em pé (Short pronto): usa o miolo
        h = int(base.width * 9 / 16)
        topo = max(0, (base.height - h) // 2)
        base = base.crop((0, topo, base.width, topo + h))
    pessoa, fracao = _pessoa(base)

    # fundo: o frame em tela cheia, mais vivo; se a pessoa já toma a tela, o fundo vai desfocado pra ela saltar
    fundo = ImageOps.fit(base, (TW, TH), Image.LANCZOS)
    fundo = ImageEnhance.Color(fundo).enhance(1.35)
    fundo = ImageEnhance.Contrast(fundo).enhance(1.15)
    if pessoa is not None and fracao > 0.08:   # câmera grande: desfoca o cenário pra pessoa saltar
        fundo = fundo.filter(ImageFilter.GaussianBlur(9))
        fundo = ImageEnhance.Brightness(fundo).enhance(0.62)
    else:                                      # câmera pequena ou sem pessoa: o jogo é a estrela, fica nítido
        fundo = fundo.filter(ImageFilter.UnsharpMask(radius=2, percent=90))
    # escurece o lado do texto (esquerda) e o rodapé, pro gancho ler em qualquer cena
    sombra = Image.new("L", (TW, TH), 0)
    ds = ImageDraw.Draw(sombra)
    for x in range(0, int(TW * 0.72), 4):
        ds.rectangle((x, 0, x + 4, TH), fill=int(190 * (1 - x / (TW * 0.72)) ** 1.3))
    fundo.paste(Image.new("RGB", (TW, TH), M.NOITE), (0, 0), sombra)
    tela = fundo.convert("RGBA")

    # streamer recortado à direita, grande, com contorno branco e brilho rosa por trás
    if pessoa is not None:
        esc = min(TH * 0.97 / pessoa.height, TW * 0.52 / pessoa.width, 2.0)  # nunca amplia mais que 2x (vira borrão)
        larg, alvo_h = int(pessoa.width * esc), int(pessoa.height * esc)
        pessoa = pessoa.resize((larg, alvo_h), Image.LANCZOS)
        if esc > 1.4:  # ampliou bastante: recupera um pouco de nitidez
            rgb = pessoa.convert("RGB").filter(ImageFilter.UnsharpMask(radius=3, percent=130, threshold=2))
            rgb.putalpha(pessoa.getchannel("A"))
            pessoa = rgb
        alfa = pessoa.getchannel("A")
        px, py = TW - larg - 24, TH - alvo_h
        borda_pessoa = px
        margem = 40
        placa = Image.new("L", (larg + 2 * margem, alvo_h + 2 * margem), 0)
        placa.paste(alfa, (margem, margem))
        brilho = placa.filter(ImageFilter.MaxFilter(31)).filter(ImageFilter.GaussianBlur(22))
        tela.paste(Image.new("RGBA", brilho.size, M.ROSA + (255,)), (px - margem, py - margem),
                   brilho.point(lambda v: int(v * 0.75)))
        contorno = placa.filter(ImageFilter.MaxFilter(17)).filter(ImageFilter.GaussianBlur(1))
        tela.paste(Image.new("RGBA", contorno.size, (255, 255, 255, 255)), (px - margem, py - margem), contorno)
        tela.paste(pessoa, (px, py), alfa)

    # gancho: 1 ou 2 linhas gigantes à esquerda, inclinadas; a primeira amarela, a segunda branca
    linhas = _linhas(gancho)
    area = int(max(TW * 0.42, borda_pessoa - 40) if pessoa is not None else TW * 0.86) - 58
    camada = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    dc = ImageDraw.Draw(camada)
    fontes = [_ajustar(l, area, 230 if len(linhas) == 1 else 190, 80) for l in linhas]
    alturas = [f.getbbox(l)[3] + 10 for f, l in zip(fontes, linhas)]
    y = (TH - sum(alturas)) // 2 - 20
    for i, (l, f) in enumerate(zip(linhas, fontes)):
        cor_l = AMARELO if i == 0 else (255, 255, 255)
        dc.text((58 + 8, y + 10), l, font=f, fill=(0, 0, 0, 255), stroke_width=12, stroke_fill=(0, 0, 0, 255))
        dc.text((58, y), l, font=f, fill=cor_l + (255,), stroke_width=12, stroke_fill=(0, 0, 0, 255))
        y += alturas[i]
    camada = camada.rotate(3.5, resample=Image.BICUBIC, center=(TW * 0.3, TH * 0.5))
    tela = Image.alpha_composite(tela, camada)

    d = ImageDraw.Draw(tela)
    if etiqueta:  # ex.: "MELHORES DO DIA", "TOP 10": placa rosa embaixo à esquerda
        f = _fonte(54)
        cx = d.textbbox((0, 0), etiqueta.upper(), font=f)
        d.rounded_rectangle((44, TH - 104, 44 + cx[2] + 44, TH - 30), radius=12, fill=M.ROSA)
        d.text((66, TH - 100), etiqueta.upper(), font=f, fill=(255, 255, 255))
    f = _fonte(30)
    d.text((TW - 190, 18), "CORTE CITY", font=f, fill=(255, 255, 255), stroke_width=3, stroke_fill=M.NOITE)

    tela.convert("RGB").save(destino, "JPEG", quality=93)
    return destino
