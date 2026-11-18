"""Quadro "gringos": rage e reação dos streamers gringos no GTA 6.

O corte sai com o ÁUDIO ORIGINAL (o grito do Speed é o conteúdo), legenda traduzida pro português
e um card no estilo post do Twitter em cima do vídeo (avatar do canal + texto curto contando o que rolou).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import FONTES, RAIZ

PROMPT = """Traduza estas falas de um streamer americano jogando GTA 6 para português do Brasil, como legenda
de corte viral do TikTok/Shorts:
- fala natural de brasileiro jovem ("bro" vira "mano", "bruh" vira "aff", "no way" vira "não acredito"...);
- curto e direto (é legenda), sem explicar nada;
- palavrão vira versão com asterisco (p*rra, m*rda, c*ralho); ofensa pesada ou xingamento a grupo: troque por "[...]";
- nomes próprios, "GTA", "Lucia", "Jason" ficam iguais;
- devolva EXATAMENTE {n} linhas, na mesma ordem.

Linhas:
{linhas}

Responda SÓ em JSON: {{"linhas": ["tradução 1", "tradução 2", ...]}}"""


def _frases(palavras: list[dict], inicio: float, fim: float) -> list[dict]:
    """Junta as palavras em frases curtas (quebra em pausa > 0,5 s, pontuação ou 7 palavras)."""
    frases, atual = [], []
    for w in palavras:
        if w["f"] < inicio or w["i"] > fim:
            continue
        if atual and (w["i"] - atual[-1]["f"] > 0.5 or len(atual) >= 7):
            frases.append(atual)
            atual = []
        atual.append(w)
        if re.search(r"[.!?]$", w["p"].strip()):
            frases.append(atual)
            atual = []
    if atual:
        frases.append(atual)
    return [{"i": f[0]["i"], "f": f[-1]["f"], "texto": " ".join(w["p"].strip() for w in f)} for f in frases]


def traduzir_legenda(palavras: list[dict], inicio: float, fim: float, endereco: str, modelo: str) -> list[dict]:
    """Devolve uma lista de palavras (mesmo formato do transcrever: p, i, f) em português, com os tempos das
    frases originais repartidos entre as palavras traduzidas. Se a IA falhar, fica a fala original."""
    from . import cerebro
    frases = _frases(palavras, inicio, fim)
    if not frases:
        return []
    linhas = "\n".join(f"{n + 1}. {f['texto']}" for n, f in enumerate(frases))
    try:
        r = cerebro._perguntar_ollama(endereco, modelo, PROMPT.format(n=len(frases), linhas=linhas))
        trad = [str(x).strip() for x in (r.get("linhas") or [])]
    except Exception as e:
        print(f"    aviso: tradução falhou ({str(e)[:100]}): legenda fica em inglês")
        trad = []
    saida = []
    for n, f in enumerate(frases):
        texto = re.sub(r"^\d+[.)]\s*", "", trad[n]) if n < len(trad) and trad[n] else f["texto"]
        ws = texto.split()
        if not ws:
            continue
        passo = max(0.08, (f["f"] - f["i"]) / len(ws))
        for k, w in enumerate(ws):
            a = f["i"] + k * passo
            saida.append({"p": w, "i": round(a, 2), "f": round(min(f["f"], a + passo), 2)})
    return saida


def _fonte(nome: str, tam: int):
    for c in (Path(FONTES) / nome, RAIZ / "assets" / "fonts" / nome):
        if c.exists():
            return ImageFont.truetype(str(c), tam)
    return ImageFont.load_default()


def _quebrar(draw, texto: str, fonte, largura: int) -> list[str]:
    linhas, atual = [], ""
    for palavra in texto.split():
        teste = f"{atual} {palavra}".strip()
        if draw.textlength(teste, font=fonte) <= largura:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


def cartao_tweet(texto: str, destino: Path, nome: str = "Corte City", arroba: str = "@cortecity",
                 avatar: Path | None = None, largura: int = 1000, altura_max: int = 600) -> tuple[int, int]:
    """Card branco no estilo post do Twitter/X. Devolve (largura, altura) da imagem gerada."""
    texto = re.sub(r"[\U00010000-\U0010FFFF]", "", re.sub(r"#\w+", "", texto or "")).strip()  # sem emoji/hashtag
    pad, av = 44, 104
    fn, fa = _fonte("Inter-ExtraBold.ttf", 40), _fonte("Inter-SemiBold.ttf", 34)
    tam = 54
    rascunho = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    while True:  # diminui a letra até caber
        ft = _fonte("Inter-SemiBold.ttf", tam)
        linhas = _quebrar(rascunho, texto, ft, largura - 2 * pad)
        alt = pad + av + 28 + len(linhas) * int(tam * 1.28) + pad
        if alt <= altura_max or tam <= 34:
            break
        tam -= 4
    img = Image.new("RGBA", (largura, alt), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, largura - 1, alt - 1], radius=36, fill=(255, 255, 255, 255))
    # avatar redondo
    if avatar and Path(avatar).exists():
        a = Image.open(avatar).convert("RGBA").resize((av, av))
        m = Image.new("L", (av, av), 0)
        ImageDraw.Draw(m).ellipse([0, 0, av - 1, av - 1], fill=255)
        fundo = Image.new("RGBA", (av, av), (12, 12, 20, 255))
        fundo.paste(a, (0, 0), a)
        img.paste(fundo, (pad, pad), m)
    else:
        d.ellipse([pad, pad, pad + av, pad + av], fill=(255, 61, 127, 255))
    x = pad + av + 24
    d.text((x, pad + 10), nome, font=fn, fill=(15, 20, 25))
    # selo azul de verificado
    nx = x + d.textlength(nome, font=fn) + 12
    d.ellipse([nx, pad + 18, nx + 34, pad + 52], fill=(29, 155, 240))
    d.line([(nx + 9, pad + 35), (nx + 15, pad + 42), (nx + 26, pad + 27)], fill=(255, 255, 255), width=5)
    d.text((x, pad + 58), arroba, font=fa, fill=(83, 100, 113))
    y = pad + av + 28
    ft = _fonte("Inter-SemiBold.ttf", tam)
    for ln in linhas:
        d.text((pad, y), ln, font=ft, fill=(15, 20, 25))
        y += int(tam * 1.28)
    img.save(destino)
    return largura, alt


def aplicar_cartao(video: Path, cartao: Path, y: int) -> None:
    """Gruda o card em cima do vídeo (o vídeo já está montado no 9:16)."""
    saida = video.with_name(video.stem + ".tweet.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(cartao),
                    "-filter_complex", f"[0:v][1:v]overlay=(W-w)/2:{max(40, y)}:format=auto,format=yuv420p[v]",
                    "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                    "-c:a", "copy", "-movflags", "+faststart", str(saida)], check=True, timeout=900)
    saida.replace(video)
