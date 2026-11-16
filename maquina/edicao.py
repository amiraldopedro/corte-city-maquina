"""Edição de editor (não de IA) para os vídeos longos: várias "batidas" dentro de cada fala.

Uma cena do roteiro pode ter "batidas": cada uma entra numa palavra da narração e troca o que está na tela.
  {"na": "Homem", "tipo": "trailer", "arquivo": "QdBZY2fkU-0", "ini": 54.0}
  {"na": "quem",  "tipo": "clipe", "fonte": "f004_piscina", "ini": 12, "credito": "WPTV"}
  {"na": "jornal","tipo": "materia", "veiculo": "Reason", "data": "3 dez 2023", "titulo": "...", "grifo": "...",
                  "url": "https://..."}
  {"na": "trinta","tipo": "numero", "numero": "33 MIL", "texto": "jacarés só no lago Okeechobee"}
  {"tipo": "comparar", "arquivo": "QdBZY2fkU-0", "ini": 42.5, "fonte": "f004_piscina", "fonte_ini": 20}
  e os tipos antigos: foto / broll / mapa (ver visuais.py).
Cada batida vira um pedaço de vídeo (1920x1080, 30 fps, com áudio: o som real do clipe baixinho + um whoosh no corte);
os pedaços são colados e viram o fundo da cena, por baixo da legenda e da narração.
"""
from __future__ import annotations

import re
import textwrap
import unicodedata
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import marca as M
from .config import FONTES
from .editar import info_video, rodar

W, H, FPS = 1920, 1080, 30
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-video_track_timescale", "15360", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]
AMARELO = (255, 201, 74)


def _f(nome: str, tam: int):
    return ImageFont.truetype(str(FONTES / nome), tam)


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


# ------------------------------------------------------------------ onde cada batida entra
def tempos(batidas: list[dict], palavras: list[dict], dur: float) -> list[tuple[float, float]]:
    """Início e fim de cada batida, pela palavra da narração em que ela entra ("na")."""
    inicios, depois = [], 0.0
    for i, b in enumerate(batidas):
        t = None
        if i == 0:
            t = 0.0
        elif b.get("na"):
            alvo = _sem_acento(b["na"])
            for p in palavras:
                w = _sem_acento(re.sub(r"[^\w]", "", p.get("p") or p.get("w", "")))
                if p["i"] >= depois + 0.2 and w.startswith(alvo):
                    t = max(0.0, p["i"] - 0.08)
                    break
        if t is None:  # sem palavra (ou não achou): divide o tempo que sobra
            t = depois + (dur - depois) / max(1, len(batidas) - i + 1) if i else 0.0
        inicios.append(t)
        depois = t
    fins = inicios[1:] + [dur]
    pares = []
    for a, b in zip(inicios, fins):
        pares.append((a, max(b, a + 0.6)))
    return pares


# ------------------------------------------------------------------ peças comuns
def _whoosh(dur: float, forte: bool = True) -> str:
    """Filtro de áudio: whoosh curto no começo e silêncio até o fim (rótulo [w])."""
    vol = 0.55 if forte else 0.3
    return (f"anoisesrc=d=0.4:c=pink:a=0.6:r=48000,highpass=f=500,lowpass=f=4200,"
            f"afade=t=in:d=0.12,afade=t=out:st=0.14:d=0.26,volume={vol},aformat=channel_layouts=stereo,"
            f"apad=whole_dur={dur:.3f}[w]")


def _zoom(dur: float, de: float = 1.0, ate: float = 1.07) -> str:
    n = int(dur * FPS) + 1
    return (f"zoompan=z='{de}+({ate}-{de})*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={W}x{H}:fps={FPS}")


def _encode(entradas: list[str], fil: list[str], dur: float, destino: Path) -> Path:
    rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", ";".join(fil),
           "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}", *X264, str(destino)])
    return destino


def _png_em_video(png: Path, dur: float, destino: Path, de=1.0, ate=1.05, extra_png: Path | None = None) -> Path:
    entradas = ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(png)]
    fil = [f"[0:v]scale={W * 2}:{H * 2},{_zoom(dur, de, ate)},format=yuv420p[z]"]
    if extra_png:
        entradas += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(extra_png)]
        fil.append("[z][1:v]overlay=0:0,format=yuv420p[v]")
    else:
        fil[-1] = fil[-1].replace("[z]", "[v]")
    fil.append(_whoosh(dur).replace("[w]", "[a]"))
    return _encode(entradas, fil, dur, destino)


# ------------------------------------------------------------------ trailer num momento escolhido
def trailer(src: Path, ini: float, dur: float, destino: Path, sentido: int = 1, rotulo: tuple | None = None) -> Path:
    de, ate = (1.0, 1.08) if sentido > 0 else (1.08, 1.0)
    entradas = ["-ss", f"{ini:.2f}", "-t", f"{dur + 0.5:.2f}", "-i", str(src)]
    fil = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},"
           f"scale={W * 2}:{H * 2},{_zoom(dur, de, ate)},eq=brightness=-0.04:saturation=1.08,format=yuv420p[v]",
           _whoosh(dur, forte=False).replace("[w]", "[a]")]
    if rotulo:
        tag = etiqueta(rotulo[0], rotulo[1], destino.with_name(destino.stem + "_rot.png"))
        entradas += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(tag)]
        fil[0] = fil[0].replace("format=yuv420p[v]", "format=yuv420p[t]")
        fil.insert(1, "[1:v]format=rgba,fade=t=in:st=0.15:d=0.25:alpha=1[r];[t][r]overlay=0:0,format=yuv420p[v]")
    return _encode(entradas, fil, dur, destino)


# ------------------------------------------------------------------ vídeo real de terceiros (citação)
def _etiqueta_fonte(texto: str, destino: Path) -> Path:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f_tag, f_fonte = _f("Anton-Regular.ttf", 44), _f("Inter-ExtraBold.ttf", 30)
    tag = "VÍDEO REAL"
    tw = int(f_tag.getlength(tag)) + 90
    x, y = 70, H - 250
    d.rectangle([x + 10, y + 10, x + tw + 10, y + 76], fill=(*M.AMEIXA, 255))
    d.rectangle([x, y, x + tw, y + 66], fill=(*M.ROSA, 255))
    d.ellipse([x + 22, y + 21, x + 46, y + 45], fill=(*M.NOITE, 255))  # bolinha "gravando"
    d.text((x + 62, y + 33), tag, font=f_tag, fill=M.NOITE, anchor="lm")
    fonte = f"Fonte: {texto}"
    fw = int(f_fonte.getlength(fonte)) + 36
    d.rectangle([x, y + 76, x + fw, y + 124], fill=(*M.NOITE, 235))
    d.text((x + 18, y + 100), fonte, font=f_fonte, fill=M.AREIA, anchor="lm")
    img.save(destino)
    return destino


def clipe(src: Path, ini: float, dur: float, credito: str, destino: Path, volume: float = 0.35) -> Path:
    """Trecho de vídeo de terceiros como citação: moldura rosa, fundo borrado, crédito na tela, som real baixinho."""
    _, _, total = info_video(src)
    ini = max(0.0, min(ini, max(0.0, total - 1.0)))
    tem = max(0.5, total - ini)
    lento = max(0.8, min(1.0, tem / dur))  # se o trecho for curto, desacelera um pouco e congela o último quadro
    tag = _etiqueta_fonte(credito, destino.with_name(destino.stem + "_tag.png"))
    larg, alt = 1480, 832
    fil = [
        f"[0:v]setpts=PTS/{lento:.3f},fps={FPS},tpad=stop_mode=clone:stop_duration={dur + 1:.2f},split[s1][s2]",
        f"[s1]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:2,eq=brightness=-0.32[bg]",
        f"[s2]scale={larg}:{alt}:force_original_aspect_ratio=decrease,pad={larg}:{alt}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"pad={larg + 16}:{alt + 16}:8:8:color=0x{M.hexa(M.ROSA)[1:]}[fg]",
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2-30[c]",
        f"[c]scale={W * 2}:{H * 2},{_zoom(dur, 1.0, 1.05)}[z]",
        "[z][1:v]overlay=0:0,format=yuv420p[v]",
        _whoosh(dur),
        f"[0:a]atempo={max(0.5, lento):.3f},volume={volume},aformat=channel_layouts=stereo,apad=whole_dur={dur:.3f}[o]",
        "[w][o]amix=inputs=2:duration=first:normalize=0[a]",
    ]
    entradas = ["-ss", f"{ini:.2f}", "-i", str(src), "-loop", "1", "-t", f"{dur:.3f}", "-i", str(tag)]
    try:
        return _encode(entradas, fil, dur, destino)
    except Exception:  # trecho sem áudio: só o whoosh
        fil = [x for x in fil if not x.startswith("[0:a]")]
        fil[-1] = "[w]anull[a]"
        return _encode(entradas, fil, dur, destino)


# ------------------------------------------------------------------ matéria de jornal com marca-texto
def _og_imagem(url: str, pasta: Path) -> Path | None:
    if not url:
        return None
    try:
        html = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}).text
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html) or \
            re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', html)
        if not m:
            return None
        img_url = m.group(1).replace("&amp;", "&")
        r = requests.get(img_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if not r.ok:
            return None
        destino = pasta / ("og_" + re.sub(r"\W", "", url)[-40:] + ".jpg")
        destino.write_bytes(r.content)
        Image.open(destino).convert("RGB").save(destino, quality=90)
        return destino
    except Exception as e:
        print(f"    matéria: sem imagem ({str(e)[:60]})")
        return None


def materia(b: dict, dur: float, pasta: Path, destino: Path) -> Path:
    """A matéria de verdade (veículo, data, manchete original e foto), com a frase importante grifada."""
    pasta.mkdir(parents=True, exist_ok=True)
    foto = _og_imagem(b.get("url", ""), pasta)
    larg = 1240
    f_veic, f_data = _f("Anton-Regular.ttf", 46), _f("Inter-SemiBold.ttf", 26)
    f_tit = _f("Inter-ExtraBold.ttf", 60) if not b.get("trecho") else _f("Inter-SemiBold.ttf", 46)
    linhas = textwrap.wrap(b.get("trecho") or b.get("titulo", ""), 34 if not b.get("trecho") else 46)[:6]
    alto_foto = 380 if foto else 0
    alto = 150 + 74 * len(linhas) + 40 + alto_foto + (30 if foto else 0)
    pag = Image.new("RGBA", (larg, alto), (250, 250, 247, 255))
    d = ImageDraw.Draw(pag)
    d.text((44, 52), b.get("veiculo", "").upper(), font=f_veic, fill=(18, 18, 22), anchor="lm")
    d.text((larg - 44, 52), b.get("data", ""), font=f_data, fill=(110, 110, 118), anchor="rm")
    d.line([(44, 96), (larg - 44, 96)], fill=(200, 200, 205), width=3)
    y0 = 130
    # onde fica o grifo (pode quebrar em mais de uma linha)
    grifo = _sem_acento(b.get("grifo", ""))
    caixas = []
    if grifo:
        texto = " ".join(linhas)
        pos = _sem_acento(texto).find(grifo)
        if pos >= 0:
            fim = pos + len(grifo)
            ofs = 0
            for k, ln in enumerate(linhas):
                a, z = max(pos, ofs), min(fim, ofs + len(ln))
                if a < z:
                    x1 = 44 + f_tit.getlength(ln[:a - ofs])
                    x2 = 44 + f_tit.getlength(ln[:z - ofs])
                    caixas.append((x1 - 6, y0 + 74 * k + 6, x2 + 6, y0 + 74 * k + 68))
                ofs += len(ln) + 1
    if foto:
        im = Image.open(foto).convert("RGB")
        esc = max((larg - 88) / im.width, alto_foto / im.height)
        im = im.resize((int(im.width * esc) + 1, int(im.height * esc) + 1))
        x0, yy = (im.width - (larg - 88)) // 2, (im.height - alto_foto) // 2
        pag.paste(im.crop((x0, yy, x0 + larg - 88, yy + alto_foto)), (44, y0 + 74 * len(linhas) + 30))
    n_quadros = 14
    quadros = []
    for q in range(n_quadros + 1):
        p = pag.copy()
        dp = ImageDraw.Draw(p)
        prog = q / n_quadros
        total = sum(c[2] - c[0] for c in caixas) or 1
        resta = prog * total
        for (x1, y1, x2, y2) in caixas:  # marca-texto passando da esquerda pra direita
            w = min(x2 - x1, resta)
            if w > 0:
                dp.rectangle([x1, y1, x1 + w, y2], fill=(*AMARELO, 255))
            resta -= (x2 - x1)
        for k, ln in enumerate(linhas):
            dp.text((44, y0 + 74 * k), ln, font=f_tit, fill=(18, 18, 22))
        # página levemente torta, com sombra, sobre o fundo da marca
        fundo = Image.new("RGB", (W, H), M.NOITE)
        gd = ImageDraw.Draw(fundo)
        for yy in range(0, H, 6):
            gd.line([(0, yy), (W, yy)], fill=(14, 20, 56))
        rot = p.rotate(-1.6, expand=True, resample=Image.BICUBIC)
        sombra = Image.new("RGBA", rot.size, (0, 0, 0, 0))
        sombra.paste((*M.AMEIXA, 255), mask=rot.split()[3])
        esc = min(W * 0.8 / rot.width, (H - 140) / rot.height)
        rot = rot.resize((int(rot.width * esc), int(rot.height * esc)))
        sombra = sombra.resize(rot.size)
        px, py = (W - rot.width) // 2, (H - rot.height) // 2 - 20
        fundo.paste(sombra, (px + 22, py + 22), sombra)
        fundo.paste(rot, (px, py), rot)
        arq = pasta / f"{destino.stem}_q{q:02d}.png"
        fundo.save(arq)
        quadros.append(arq)
    # 0,35 s parado, marca-texto em ~0,5 s, depois segura
    seq = pasta / f"{destino.stem}_seq.txt"
    linhas_seq = [f"file '{quadros[0].name}'\nduration 0.35"]
    linhas_seq += [f"file '{a.name}'\nduration {0.5 / n_quadros:.4f}" for a in quadros[1:]]
    linhas_seq += [f"file '{quadros[-1].name}'\nduration {max(0.2, dur - 0.85):.3f}", f"file '{quadros[-1].name}'"]
    seq.write_text("\n".join(linhas_seq))
    fil = [f"[0:v]fps={FPS},scale={W * 2}:{H * 2},{_zoom(dur, 1.0, 1.06)},format=yuv420p[v]",
           _whoosh(dur).replace("[w]", "[a]")]
    return _encode(["-f", "concat", "-safe", "0", "-i", str(seq)], fil, dur, destino)


# ------------------------------------------------------------------ número gigante
def numero(b: dict, dur: float, destino: Path, fundo_src: Path | None = None, fundo_ini: float = 0) -> Path:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    num = b.get("numero", "")
    tam = 300 if len(num) <= 6 else (220 if len(num) <= 10 else 150)
    f_num, f_txt = _f("Anton-Regular.ttf", tam), _f("Inter-ExtraBold.ttf", 54)
    cy = H // 2 - 60
    d.text((W // 2 + 14, cy + 14), num, font=f_num, fill=(*M.AMEIXA, 255), anchor="mm")
    d.text((W // 2, cy), num, font=f_num, fill=(*M.ROSA, 255), anchor="mm", stroke_width=6, stroke_fill=M.NOITE)
    if b.get("texto"):
        t = b["texto"]
        tw = int(f_txt.getlength(t)) + 60
        ty = cy + tam // 2 + 50
        d.rectangle([(W - tw) // 2, ty - 42, (W + tw) // 2, ty + 42], fill=(*M.NOITE, 240))
        d.rectangle([(W - tw) // 2, ty - 42, (W - tw) // 2 + 10, ty + 42], fill=(*M.AZUL, 255))
        d.text((W // 2 + 5, ty), t, font=f_txt, fill=M.AREIA, anchor="mm")
    camada = destino.with_name(destino.stem + "_num.png")
    img.save(camada)
    if fundo_src:  # número por cima do trailer escurecido e borrado
        fil = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},"
               f"boxblur=18:2,eq=brightness=-0.35:saturation=1.2[bg]",
               f"[1:v]format=rgba,scale=w='{W}*(1.18-0.18*min(1,t/0.22))':h=-1:eval=frame[n]",
               "[bg][n]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]", _whoosh(dur).replace("[w]", "[a]")]
        return _encode(["-ss", f"{fundo_ini:.2f}", "-t", f"{dur + 0.5:.2f}", "-i", str(fundo_src),
                        "-loop", "1", "-t", f"{dur:.3f}", "-i", str(camada)], fil, dur, destino)
    base = Image.new("RGB", (W, H), M.NOITE)
    base.paste(img, (0, 0), img)
    png = destino.with_suffix(".png")
    base.save(png)
    return _png_em_video(png, dur, destino, 1.12, 1.0)


# ------------------------------------------------------------------ GTA 6 x vida real (os dois se mexendo)
def comparar(esq: Path, esq_ini: float, dir_src: Path, dir_ini: float, dur: float, rotulos: list[str],
             destino: Path, dir_e_foto: bool = False) -> Path:
    meia = W // 2
    rot = destino.with_name(destino.stem + "_rot.png")
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([meia - 5, 0, meia + 5, H], fill=(*M.ROSA, 255))
    f = _f("Anton-Regular.ttf", 58)
    for i, texto in enumerate((rotulos or ["GTA 6", "VIDA REAL"])[:2]):
        tw = int(f.getlength(texto)) + 48
        x = 50 if i == 0 else meia + 50
        cor = M.AZUL if i == 0 else M.ROSA
        d.rectangle([x + 8, 58, x + tw + 8, 146], fill=(*M.AMEIXA, 255))
        d.rectangle([x, 50, x + tw, 138], fill=(*cor, 255))
        d.text((x + tw // 2, 94), texto, font=f, fill=M.NOITE, anchor="mm")
    img.save(rot)
    if dir_e_foto:
        entrada_dir = ["-loop", "1", "-t", f"{dur + 0.5:.2f}", "-i", str(dir_src)]
    else:
        entrada_dir = ["-ss", f"{dir_ini:.2f}", "-i", str(dir_src)]
    fil = [
        f"[0:v]scale=-2:{H},crop={meia}:{H},setsar=1,fps={FPS}[a]",
        f"[1:v]fps={FPS},tpad=stop_mode=clone:stop_duration={dur + 1:.2f},scale={meia}:{H}:force_original_aspect_ratio=increase,"
        f"crop={meia}:{H},setsar=1[b]",
        f"[a]pad={W}:{H}:0:0[a2]",
        f"[a2][b]overlay=x='if(lt(t,0.45),{W}-{meia}*t/0.45,{meia})':y=0[c]",  # o lado real entra deslizando
        "[c][2:v]overlay=0:0,format=yuv420p[v]",
        _whoosh(dur).replace("[w]", "[a]"),
    ]
    return _encode(["-ss", f"{esq_ini:.2f}", "-t", f"{dur + 0.5:.2f}", "-i", str(esq), *entrada_dir,
                    "-loop", "1", "-t", f"{dur:.3f}", "-i", str(rot)], fil, dur, destino)


# ------------------------------------------------------------------ silêncio com imagem (pedaços antigos sem áudio)
def com_audio(video: Path, dur: float, destino: Path) -> Path:
    fil = [f"[0:v]scale={W}:{H},setsar=1,fps={FPS},format=yuv420p[v]", _whoosh(dur, forte=False).replace("[w]", "[a]")]
    return _encode(["-i", str(video)], fil, dur, destino)


def colar(pedacos: list[Path], destino: Path) -> Path:
    lista = destino.with_suffix(".txt")
    lista.write_text("\n".join(f"file '{p.resolve()}'" for p in pedacos))
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lista),
           "-c", "copy", str(destino)])
    return destino


# ------------------------------------------------------------------ mapa de capítulos (estilo "hub")
CAPITULOS_PADRAO = ["A polícia", "O corpo", "A dupla", "As armas", "Os carros", "O dinheiro", "As pessoas", "O mundo"]


def capitulo(b: dict, dur: float, destino: Path, fundo_src: Path | None = None, fundo_ini: float = 0) -> Path:
    """Os capítulos como pontos ligados num círculo; o atual acende em rosa, e o título entra ao lado."""
    import math
    nomes = b.get("lista") or CAPITULOS_PADRAO
    atual = b.get("atual", 0)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy, r = 480, H // 2, 270
    pts = [(cx + r * math.cos(-math.pi / 2 + 2 * math.pi * k / len(nomes)),
            cy + r * math.sin(-math.pi / 2 + 2 * math.pi * k / len(nomes))) for k in range(len(nomes))]
    for k in range(len(pts)):
        a, z = pts[k], pts[(k + 1) % len(pts)]
        cor = (*M.ROSA, 255) if k < atual else (120, 130, 170, 140)
        d.line([a, z], fill=cor, width=5 if k < atual else 3)
    f_n = _f("Inter-ExtraBold.ttf", 26)
    for k, (x, y) in enumerate(pts):
        feito, agora = k < atual, k == atual
        raio = 46 if agora else 32
        if agora:
            d.ellipse([x - raio - 16, y - raio - 16, x + raio + 16, y + raio + 16], fill=(*M.ROSA, 70))
        d.ellipse([x - raio, y - raio, x + raio, y + raio],
                  fill=(*(M.ROSA if (feito or agora) else M.NOITE), 255), outline=(*M.AREIA, 255), width=4)
        d.text((x, y), f"{k + 1:02d}", font=f_n, fill=M.NOITE if (feito or agora) else M.AREIA, anchor="mm")
        lx = x + (70 if x >= cx else -70)
        d.text((lx, y), nomes[k].upper(), font=f_n, fill=(*M.AREIA, 255 if agora else 170),
               anchor="lm" if x >= cx else "rm")
    f_parte, f_tit = _f("Inter-ExtraBold.ttf", 40), _f("Anton-Regular.ttf", 150)
    d.text((1120, H // 2 - 120), f"PARTE {atual + 1:02d}", font=f_parte, fill=(*M.AZUL, 255), anchor="lm")
    d.text((1128, H // 2 + 18), nomes[atual].upper(), font=f_tit, fill=(*M.AMEIXA, 255), anchor="lm")
    d.text((1120, H // 2 + 10), nomes[atual].upper(), font=f_tit, fill=(*M.ROSA, 255), anchor="lm")
    camada = destino.with_name(destino.stem + "_cap.png")
    img.save(camada)
    if fundo_src:
        fil = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},"
               f"boxblur=22:2,eq=brightness=-0.42:saturation=0.9[bg]",
               "[1:v]format=rgba,fade=t=in:st=0:d=0.25:alpha=1[n]",
               "[bg][n]overlay=0:0,format=yuv420p[v]", _whoosh(dur).replace("[w]", "[a]")]
        return _encode(["-ss", f"{fundo_ini:.2f}", "-t", f"{dur + 0.5:.2f}", "-i", str(fundo_src),
                        "-loop", "1", "-t", f"{dur:.3f}", "-i", str(camada)], fil, dur, destino)
    base = Image.new("RGB", (W, H), M.NOITE)
    base.paste(img, (0, 0), img)
    png = destino.with_suffix(".png")
    base.save(png)
    return _png_em_video(png, dur, destino, 1.0, 1.04)


# ------------------------------------------------------------------ painel de procurado (desenho nosso, não o HUD do jogo)
def procurado(b: dict, dur: float, destino: Path, fundo_src: Path | None = None, fundo_ini: float = 0) -> Path:
    """Estrelas de procurado e o que a polícia sabe; os itens riscados somem um a um."""
    estrelas, total = int(b.get("estrelas", 3)), int(b.get("total", 6))
    itens = b.get("itens") or ["ROSTO", "ROUPA", "ARMA", "CARRO", "PARCEIRO", "CÂMERA"]
    riscar = b.get("riscar", [])
    n = 18
    quadros = []
    pasta = destino.parent
    for q in range(n + 1):
        p = q / n
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        x0, y0 = 1180, 140
        d.rounded_rectangle([x0 - 40, y0 - 40, W - 80, y0 + 470], 28, fill=(*M.NOITE, 215), outline=(*M.ROSA, 255), width=4)
        for k in range(total):
            cx, cy, r = x0 + 50 + k * 100, y0 + 50, 40
            pts = []
            import math
            for j in range(10):
                ang = -math.pi / 2 + j * math.pi / 5
                rr = r if j % 2 == 0 else r * 0.45
                pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
            acesa = k < estrelas
            d.polygon(pts, fill=(*(M.AMARELO_SOL if hasattr(M, "AMARELO_SOL") else AMARELO), 255) if acesa else (60, 66, 100, 255))
        f = _f("Inter-ExtraBold.ttf", 34)
        for k, it in enumerate(itens):
            cx, cy = x0 + (k % 3) * 205, y0 + 180 + (k // 3) * 130
            some = it in riscar and p > (0.25 + 0.6 * riscar.index(it) / max(1, len(riscar)))
            cor = (110, 115, 140, 255) if some else (*M.AREIA, 255)
            d.rounded_rectangle([cx - 10, cy - 40, cx + 180, cy + 40], 14, fill=(*(M.OCEANO if not some else M.NOITE), 255))
            d.text((cx + 85, cy), it, font=f, fill=cor, anchor="mm")
            if some:
                d.line([(cx - 4, cy), (cx + 174, cy)], fill=(*M.ROSA, 255), width=6)
        arq = pasta / f"{destino.stem}_p{q:02d}.png"
        img.save(arq)
        quadros.append(arq)
    seq = pasta / f"{destino.stem}_seq.txt"
    passo = max(0.04, (dur * 0.85) / n)
    seq.write_text("\n".join([f"file '{a.name}'\nduration {passo:.4f}" for a in quadros] +
                             [f"file '{quadros[-1].name}'\nduration {max(0.2, dur - passo * n):.3f}", f"file '{quadros[-1].name}'"]))
    src, ini = fundo_src, fundo_ini
    fil = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},eq=brightness=-0.12[bg]",
           f"[1:v]fps={FPS},format=rgba[n]", "[bg][n]overlay=0:0,format=yuv420p[v]", _whoosh(dur).replace("[w]", "[a]")]
    return _encode(["-ss", f"{ini:.2f}", "-t", f"{dur + 0.5:.2f}", "-i", str(src),
                    "-f", "concat", "-safe", "0", "-i", str(seq)], fil, dur, destino)


# ------------------------------------------------------------------ nome de quem falou (sem foto)
def etiqueta(nome: str, cargo: str, destino: Path) -> Path:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f_n, f_c = _f("Anton-Regular.ttf", 62), _f("Inter-ExtraBold.ttf", 30)
    x, y = 90, H - 330
    wn = int(f_n.getlength(nome.upper())) + 50
    wc = int(f_c.getlength(cargo.upper())) + 40
    d.rectangle([x, y, x + wn, y + 86], fill=(*M.AREIA, 255))
    d.text((x + 25, y + 43), nome.upper(), font=f_n, fill=M.NOITE, anchor="lm")
    d.rectangle([x, y + 86, x + wc, y + 132], fill=(*M.ROSA, 255))
    d.text((x + 20, y + 109), cargo.upper(), font=f_c, fill=M.NOITE, anchor="lm")
    img.save(destino)
    return destino


# ------------------------------------------------------------------ screenshot oficial em 4K (tela cheia, com movimento)
def oficial(img: Path, dur: float, destino: Path, foco: tuple = (0.5, 0.5), de: float = 1.0, ate: float = 1.12) -> Path:
    """Imagem oficial em tela cheia, empurrando devagar na direção do foco (x, y de 0 a 1)."""
    fx, fy = foco
    n = int(dur * FPS) + 1
    z = f"{de}+({ate}-{de})*on/{n}"
    fil = [f"[0:v]scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},setsar=1,"
           f"zoompan=z='{z}':x='(iw-iw/zoom)*{fx}':y='(ih-ih/zoom)*{fy}':d={n}:s={W}x{H}:fps={FPS},format=yuv420p[v]",
           _whoosh(dur, forte=False).replace("[w]", "[a]")]
    return _encode(["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", str(img)], fil, dur, destino)
