"""Contagem regressiva pro GTA 6: Shorts 9:16 narrados, um por dia, conteúdo 100% próprio.

Roteiros em roteiros/contagem/*.json:
  {"id": "faltam5", "selo": "FALTAM 5 DIAS", "publicar": "2026-11-14T12:00", "titulo": "...", "descricao": "...",
   "tags": [...], "cenas": [{"texto": "fala", "card": {"tipo": "dado|lista|texto|nenhum", ...}}]}
Visual: imagens dos trailers oficiais da biblioteca (sem o som), selo rosa fixo no topo,
um card por cena no meio, legenda karaokê Vice embaixo, CC de marca d'água e barra azul.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import marca as M
from .config import FONTES, RAIZ
from .editar import _escapar, gerar_legenda, info_video, rodar

W, H, FPS = 1080, 1920, 30
PASTA_ROTEIROS = RAIZ / "roteiros" / "contagem"


def _f(nome: str, tam: int):
    return ImageFont.truetype(str(FONTES / nome), tam)


def selo(texto: str, destino: Path) -> Path:
    """Placa rosa "FALTAM 5 DIAS" com sombra dura ameixa (fica o vídeo inteiro no topo)."""
    f = _f("Anton-Regular.ttf", 118)
    lw = int(f.getlength(texto)) + 90
    img = Image.new("RGBA", (lw + 16, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([16, 16, lw + 15, 191], fill=(*M.AMEIXA, 255))
    d.rectangle([0, 0, lw - 1, 175], fill=(*M.ROSA, 255))
    d.text((lw // 2, 88), texto, font=f, fill=M.NOITE, anchor="mm")
    img.save(destino)
    return destino


def card(c: dict, destino: Path) -> Path | None:
    tipo = c.get("tipo", "nenhum")
    if tipo == "nenhum":
        return None
    larg = 960
    if tipo == "dado":
        f1, f2 = _f("Anton-Regular.ttf", 200), _f("Inter-ExtraBold.ttf", 54)
        num = str(c.get("numero", ""))
        while f1.getlength(num) > larg - 100 and f1.size > 90:
            f1 = _f("Anton-Regular.ttf", f1.size - 10)
        linhas = textwrap.wrap(c.get("texto", ""), 26)[:3]
        alto = 70 + f1.size + 30 + 68 * len(linhas) + 50
        img = Image.new("RGBA", (larg, alto), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, larg - 1, alto - 1], 36, fill=(*M.OCEANO, 235), outline=M.AZUL, width=5)
        d.text((larg // 2, 60 + f1.size // 2), num, font=f1, fill=M.AZUL, anchor="mm")
        y = 70 + f1.size + 30
        for ln in linhas:
            d.text((larg // 2, y + 26), ln, font=f2, fill=M.AREIA, anchor="mm")
            y += 68
    elif tipo == "lista":
        itens = [str(i) for i in c.get("itens", [])][:6]
        f = _f("Inter-ExtraBold.ttf", 50)
        alto = 60 + 104 * len(itens) + 20
        img = Image.new("RGBA", (larg, alto), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, larg - 1, alto - 1], 36, fill=(*M.OCEANO, 235), outline=M.AZUL, width=5)
        y = 50
        for n, it in enumerate(itens, 1):
            d.ellipse([50, y, 122, y + 72], fill=M.ROSA)
            d.text((86, y + 37), str(n), font=_f("Anton-Regular.ttf", 46), fill=M.NOITE, anchor="mm")
            d.text((150, y + 10), it[:28], font=f, fill=M.AREIA)
            y += 104
    else:  # texto grande
        f = _f("Anton-Regular.ttf", 108)
        linhas = textwrap.wrap(c.get("texto", "").upper(), 16)[:4]
        alto = 80 + 120 * len(linhas)
        img = Image.new("RGBA", (larg, alto), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        y = 40
        for i, ln in enumerate(linhas):
            cor = M.AZUL if i == len(linhas) - 1 and len(linhas) > 1 else M.AREIA
            d.text((larg // 2 + 7, y + 67), ln, font=f, fill=M.AMEIXA, anchor="mm")
            d.text((larg // 2, y + 60), ln, font=f, fill=cor, anchor="mm", stroke_width=5, stroke_fill=M.NOITE)
            y += 120
    img.save(destino)
    return destino


def montar(roteiro: dict, fontes: list[Path], pasta: Path, log=print) -> Path:
    """Narra cena a cena, monta o fundo com os trailers e junta tudo num Short pronto."""
    from .narrado import Fundos, falar
    pasta.mkdir(parents=True, exist_ok=True)
    voz, taxa = roteiro.get("voz", "pt-BR-AntonioNeural"), roteiro.get("taxa", "+10%")
    fundos = Fundos(fontes, semente=sum(map(ord, roteiro["id"])))
    s = selo(roteiro["selo"], pasta / "selo.png")
    partes, palavras, relogio = [], [], 0.0
    for i, c in enumerate(roteiro["cenas"]):
        audio = pasta / f"c{i:02d}.mp3"
        ps = falar(c["texto"], voz, taxa, audio)
        dur = (ps[-1]["f"] if ps else 3) + 0.25
        palavras += [{**p, "i": p["i"] + relogio, "f": p["f"] + relogio} for p in ps]
        src, ini = fundos.trecho(dur)
        cd = card(c.get("card", {}), pasta / f"c{i:02d}.png")
        entradas = ["-ss", f"{ini:.2f}", "-t", f"{dur:.2f}", "-i", str(src), "-i", str(audio), "-i", str(s)]
        lado = 1 if i % 2 else -1
        x = f"(iw-ow)*t/{dur:.2f}" if lado > 0 else f"(iw-ow)*(1-t/{dur:.2f})"
        fil = [f"[0:v]scale=-2:{H + 120},crop={W + 160}:{H + 120},setsar=1,fps={FPS},"
               f"crop={W}:{H}:x='{x}':y='(ih-oh)/2',eq=brightness=-0.16:saturation=1.1[b0]",
               "[2:v]format=rgba[s]", "[b0][s]overlay=x=(W-w)/2:y=170[b1]"]
        atual, n = "b1", 3
        if cd:
            entradas += ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(cd)]
            alto_card = Image.open(cd).height
            y_card = max(430, 820 - alto_card // 2)
            fil.append(f"[{n}:v]format=rgba,fade=t=in:st=0.1:d=0.3:alpha=1[k]")
            fil.append(f"[{atual}][k]overlay=x='(W-w)/2':y='if(lt(t,0.4),{y_card}+60-150*t,{y_card})'[b2]")
            atual, n = "b2", n + 1
        fil.append(f"[{atual}]format=yuv420p[v]")
        parte = pasta / f"c{i:02d}.mp4"
        rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", ";".join(fil),
               "-map", "[v]", "-map", "1:a", "-af", f"apad,atrim=0:{dur:.2f},aresample=48000",
               "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(parte)])
        partes.append(parte)
        relogio += dur
        log(f"  cena {i + 1}/{len(roteiro['cenas'])} ok ({dur:.1f}s)")
    lista = pasta / "lista.txt"
    lista.write_text("".join(f"file '{p.name}'\n" for p in partes))
    juntado = pasta / "juntado.mp4"
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy",
           str(juntado)])
    total = info_video(juntado)[2]
    ass = pasta / "legenda.ass"
    gerar_legenda(palavras, 0, total, ass, 1520, M.hexa(M.ROSA))
    final = pasta / f"{roteiro['id']}.mp4"
    marca = M.MONOGRAMA
    barra = "0x" + M.hexa(M.AZUL).lstrip("#")
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", str(juntado), "-i", str(marca), "-filter_complex",
           f"[1:v]scale=150:-1,format=rgba,colorchannelmixer=aa=0.85[m];[0:v][m]overlay=W-w-28:40[v1];"
           f"[v1]ass='{_escapar(ass)}':fontsdir='{_escapar(FONTES)}',"
           f"drawbox=x=0:y=0:w='iw*t/{total:.2f}':h=12:color={barra}@1:t=fill,format=yuv420p[v]",
           "-map", "[v]", "-map", "0:a", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", str(final)])
    return final


def roteiros() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(PASTA_ROTEIROS.glob("*.json"))]
