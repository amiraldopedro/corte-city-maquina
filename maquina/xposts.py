"""Post do X -> Short: o post como a pessoa postou (texto + foto/vídeo), num template de post, com crédito.

Os dados vêm do endpoint público que o próprio X usa nos posts incorporados em sites
(cdn.syndication.twimg.com), sem login e sem chave. Post marcado pelo X como sensível é barrado.
"""
from __future__ import annotations

import math
import re
import subprocess
import textwrap
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import marca as M
from .config import FONTES
from .noticias import UA, bloqueado

W, H = 1080, 1920
CARD_W = 980


def id_do_post(link: str) -> str:
    m = re.search(r"/status(?:es)?/(\d+)", link)
    if not m:
        raise ValueError("link de post do X inválido")
    return m.group(1)


def _token(pid: str) -> str:
    """Mesmo cálculo do widget oficial de incorporação."""
    n = (int(pid) / 1e15) * math.pi
    inteiro, frac = int(n), n - int(n)
    dig = "0123456789abcdefghijklmnopqrstuvwxyz"
    s = ""
    while inteiro:
        inteiro, r = divmod(inteiro, 36)
        s = dig[r] + s
    s = (s or "0") + "."
    for _ in range(12):
        frac *= 36
        s += dig[int(frac)]
        frac -= int(frac)
    return re.sub(r"(0+|\.)", "", s)


def buscar(link: str) -> dict:
    pid = id_do_post(link)
    r = requests.get("https://cdn.syndication.twimg.com/tweet-result", headers=UA, timeout=30,
                     params={"id": pid, "token": _token(pid), "lang": "pt"})
    r.raise_for_status()
    d = r.json()
    if d.get("__typename") == "TweetTombstone" or "user" not in d:
        raise LookupError("post apagado, protegido ou indisponível")
    u = d["user"]
    texto = re.sub(r"\s*https://t\.co/\S+$", "", d.get("text", "")).strip()
    for e in (d.get("entities") or {}).get("urls", []):  # link encurtado -> link legível
        texto = texto.replace(e.get("url", "~"), e.get("display_url", ""))
    midias = []
    for m in d.get("mediaDetails") or []:
        if m.get("type") == "photo":
            midias.append({"tipo": "foto", "url": m["media_url_https"] + "?name=large"})
        elif m.get("type") in ("video", "animated_gif"):
            mp4 = [v for v in (m.get("video_info") or {}).get("variants", []) if v.get("content_type") == "video/mp4"]
            if mp4:
                midias.append({"tipo": "video", "url": max(mp4, key=lambda v: v.get("bitrate", 0))["url"],
                               "capa": m.get("media_url_https")})
    return {
        "id": "x_" + pid, "origem": "x", "link": f"https://x.com/{u['screen_name']}/status/{pid}",
        "autor": u.get("name", ""), "perfil": u.get("screen_name", ""),
        "avatar": (u.get("profile_image_url_https") or "").replace("_normal", "_200x200"),
        "verificado": bool(u.get("is_blue_verified") or u.get("verified")),
        "texto": texto, "idioma": d.get("lang", ""), "data": d.get("created_at", ""),
        "curtidas": d.get("favorite_count", 0), "sensivel": bool(d.get("possibly_sensitive")),
        "midias": midias, "fonte": f"{u.get('name', '')} (@{u.get('screen_name', '')})",
        "titulo_fonte": texto,
    }


VAZAMENTO = re.compile(r"vaza|vazou|vazad|leak|datamin|build interna|source code|código fonte", re.I)
SENSIVEL = re.compile(r"nsfw|porn|nud[eo]|sexo|sexual|onlyfans|\+18|18\+|nazi|suic|estupr|pedof|"
                      r"morte de|morreu|assassin|tiroteio real|atentado", re.I)


def seguro(post: dict) -> tuple[bool, str]:
    """Conversa sobre leaker/vazamento pode (meme, opinião). O que não pode é MOSTRAR material vazado:
    post que fala de vazamento E traz foto/vídeo é barrado. Adulto/sensível é sempre barrado."""
    if post["sensivel"]:
        return False, "o X marcou como conteúdo sensível"
    if SENSIVEL.search(post["texto"]):
        return False, "assunto sensível"
    if VAZAMENTO.search(post["texto"]) and post["midias"]:
        return False, "fala de vazamento e traz imagem/vídeo (pode ser o material vazado)"
    return True, ""


# ------------------------------------------------------------------ desenho do post
def _baixar(url: str, destino: Path) -> Path:
    r = requests.get(url, headers=UA, timeout=120)
    r.raise_for_status()
    destino.write_bytes(r.content)
    return destino


def _fmt(n: int) -> str:
    t = f"{n / 1e6:.1f} mi" if n >= 1e6 else f"{n / 1e3:.1f} mil" if n >= 1e3 else str(n)
    return t.replace(".0 ", " ").replace(".", ",")  # 18,4 mil (jeito brasileiro)


LINGUAS = {"en": "inglês", "es": "espanhol", "ja": "japonês", "fr": "francês", "de": "alemão", "it": "italiano",
           "ko": "coreano", "ru": "russo", "zh": "chinês", "ar": "árabe", "pl": "polonês", "tr": "turco", "nl": "holandês"}


def traduzir(post: dict, perguntar, idioma_canal: str = "pt") -> bool:
    """Post em outra língua: o texto do card vira português (tradução fiel, sem reescrever o sentido).
    O original fica guardado em post["texto_original"] e vai pra descrição. Devolve True se traduziu."""
    lingua = (post.get("idioma") or "")[:2]
    texto = (post.get("texto") or "").strip()
    if not texto or lingua in (idioma_canal, "", "un", "zx", "qm", "qs", "qh"):  # sem texto / só emoji / só link
        return False
    nome = LINGUAS.get(lingua, "outra língua")
    r = perguntar(
        "Traduza este post do X para português do Brasil, de forma fiel e natural, como um brasileiro escreveria. "
        "Mantenha @menções, #hashtags, números, nomes próprios e emojis como estão. Não acrescente nem tire nada, "
        "não explique, não comente. Se for gíria ou meme, use a gíria equivalente em português. "
        f'Post ({nome}): """{texto[:1500]}""". Responda só com JSON: {{"traducao": "..."}}')
    traducao = str((r or {}).get("traducao", "")).strip().strip('"')
    if len(traducao) < max(3, len(texto) * 0.3):
        raise RuntimeError("tradução veio vazia ou curta demais")
    post["texto_original"] = texto
    post["texto"] = traducao
    post["traduzido_de"] = nome
    post["idioma"] = idioma_canal
    return True


def cartao(post: dict, pasta: Path, cor: str, alto_midia: int) -> tuple[Path, tuple[int, int, int, int]]:
    """Desenha o post (cabeçalho + texto + espaço da mídia + rodapé).
    Devolve o PNG e a caixa (x, y, w, h) onde a foto/vídeo entra, já na posição da tela."""
    f_nome = ImageFont.truetype(str(FONTES / "Inter-ExtraBold.ttf"), 40)
    f_user = ImageFont.truetype(str(FONTES / "Inter-SemiBold.ttf"), 32)
    # a fonte do card não tem emoji: tira pra não aparecer quadradinho "NO GLYPH"
    texto = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]", "", post["texto"])
    texto = re.sub(r"[ \t]{2,}", " ", texto).strip()
    tam = 46 if len(texto) < 120 else 40 if len(texto) < 220 else 34
    f_txt = ImageFont.truetype(str(FONTES / "Inter-SemiBold.ttf"), tam)
    largura_chars = int((CARD_W - 100) / (tam * 0.56))
    linhas = []
    for par in texto.split("\n"):
        linhas += textwrap.wrap(par, largura_chars) or [""]
    linhas = linhas[:14]
    pad, topo = 50, 50
    y_txt = topo + 110
    alt_txt = int(len(linhas) * tam * 1.32) if texto else 0
    f_trad = ImageFont.truetype(str(FONTES / "Inter-SemiBold.ttf"), 28)
    alt_trad = 50 if post.get("traduzido_de") else 0
    y_midia = y_txt + alt_txt + alt_trad + (30 if texto else 0)
    alto = y_midia + (alto_midia + 30 if alto_midia else 0) + 80
    img = Image.new("RGBA", (CARD_W, alto), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, CARD_W - 1, alto - 1], 40, fill=(*M.OCEANO, 245), outline=M.AZUL, width=5)
    # avatar
    try:
        av = Image.open(_baixar(post["avatar"], pasta / "avatar.jpg")).convert("RGB").resize((96, 96))
    except Exception:
        av = Image.new("RGB", (96, 96), cor)
    masc = Image.new("L", (96, 96), 0)
    ImageDraw.Draw(masc).ellipse([0, 0, 95, 95], fill=255)
    img.paste(av, (pad, topo), masc)
    nome = post["autor"][:26]
    d.text((pad + 120, topo + 6), nome, font=f_nome, fill=M.AREIA)
    if post["verificado"]:
        x = pad + 120 + int(f_nome.getlength(nome)) + 14
        d.ellipse([x, topo + 14, x + 34, topo + 48], fill=(29, 155, 240))
        d.line([(x + 9, topo + 31), (x + 15, topo + 38), (x + 26, topo + 23)], fill=(255, 255, 255), width=5)
    d.text((pad + 120, topo + 56), "@" + post["perfil"], font=f_user, fill=M.NEVOA)
    y = y_txt
    for ln in linhas:
        d.text((pad, y), ln, font=f_txt, fill=M.AREIA)
        y += int(tam * 1.32)
    if post.get("traduzido_de"):  # deixa claro que o texto foi traduzido (o original vai na descrição)
        d.text((pad, y + 12), f"Traduzido do {post['traduzido_de']} pela Corte City", font=f_trad, fill=M.CIANO)
    rodape = []
    try:
        rodape.append(datetime.fromisoformat(post["data"].replace("Z", "+00:00")).strftime("%d/%m/%Y"))
    except Exception:
        pass
    if post["curtidas"]:
        rodape.append(f"{_fmt(post['curtidas'])} curtidas")
    rodape.append("Post no X")
    d.text((pad, alto - 62), "   •   ".join(rodape), font=f_user, fill=M.NEVOA)
    destino = pasta / "post.png"
    img.save(destino)
    x0, y0 = (W - CARD_W) // 2, (H - alto) // 2 + 40
    return destino, (x0 + pad, y0 + y_midia, CARD_W - 2 * pad, alto_midia), (x0, y0)


def montar(post: dict, pasta: Path, cor: str, marca: Path | None, chamada: str, narrar=None) -> Path:
    """Short 9:16. Vídeo: toca dentro do post com o som original. Foto/texto: o post na tela,
    com zoom leve, e a voz lendo o texto da pessoa (sem a IA reescrever)."""
    from . import editar
    pasta.mkdir(parents=True, exist_ok=True)
    video = next((m for m in post["midias"] if m["tipo"] == "video"), None)
    fotos = [m for m in post["midias"] if m["tipo"] == "foto"][:4]
    midia_arq, alto_midia, dur, audio = None, 0, 0.0, None
    larg_midia = CARD_W - 100
    if video:
        midia_arq = _baixar(video["url"], pasta / "midia.mp4")
        lw, lh, dur = editar.info_video(midia_arq)
        dur = min(dur, 58.0)
        alto_midia = min(int(larg_midia * lh / max(lw, 1)), 1000) // 2 * 2
    elif fotos:
        imgs = [Image.open(_baixar(f["url"], pasta / f"foto{i}.jpg")).convert("RGB") for i, f in enumerate(fotos)]
        if len(imgs) == 1:
            alto_midia = min(int(larg_midia * imgs[0].height / imgs[0].width), 1000) // 2 * 2
            grade = ImageOps.fit(imgs[0], (larg_midia, alto_midia))
        else:
            alto_midia = 700
            grade = Image.new("RGB", (larg_midia, alto_midia), (0, 0, 0))
            cols = 2
            linhas = math.ceil(len(imgs) / cols)
            cw, ch = (larg_midia - 8) // cols, (alto_midia - 8 * (linhas - 1)) // linhas
            for i, im in enumerate(imgs):
                grade.paste(ImageOps.fit(im, (cw, ch)), ((i % cols) * (cw + 8), (i // cols) * (ch + 8)))
        midia_arq = pasta / "midia.png"
        grade.save(midia_arq)
    card, caixa, (cx, cy) = cartao(post, pasta, cor, alto_midia)
    if not video:
        if narrar and post["texto"]:
            audio = pasta / "voz.mp3"
            palavras = narrar(post["texto"], audio)
            dur = (palavras[-1]["f"] if palavras else 6) + 1.2
        else:
            dur = max(7.0, min(18.0, len(post["texto"].split()) * 0.4 + 4))
    dur = max(dur, 5.0)
    legenda = pasta / "chamada.ass"
    editar.gerar_legenda([], 0, dur, legenda, 1700, cor, chamada=chamada, y_chamada=max(240, cy - 70),
                         etiqueta="COMUNIDADE")
    # fundo: a própria mídia borrada (ou o cartão), escurecida
    fundo_src = midia_arq if midia_arq else card
    entradas, fil = [], []
    if video:
        entradas += ["-i", str(midia_arq)]
        fil.append("[0:v]split[v_a][v_b]")
        fil.append(f"[v_a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:3,"
                   f"eq=brightness=-0.25,setsar=1,fps=30[bg]")
        fil.append(f"[v_b]scale={caixa[2]}:{caixa[3]}:force_original_aspect_ratio=decrease,"
                   f"pad={caixa[2]}:{caixa[3]}:(ow-iw)/2:(oh-ih)/2:color=0x0A0E2A,setsar=1,fps=30[mid]")
        idx_card = 1
    else:
        entradas += ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(fundo_src)]
        fil.append(f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:3,"
                   f"eq=brightness=-0.3,setsar=1,fps=30[bg]")
        idx_card = 1
    entradas += ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(card)]
    fil.append(f"[bg][{idx_card}:v]overlay={cx}:{cy}[c0]")
    prox = idx_card + 1
    if video:
        fil.append(f"[c0][mid]overlay={caixa[0]}:{caixa[1]}[c1]")
    elif fotos:
        entradas += ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(midia_arq)]
        fil.append(f"[c0][{prox}:v]overlay={caixa[0]}:{caixa[1]}[c1]")
        prox += 1
    else:
        fil.append("[c0]null[c1]")
    if marca and Path(marca).exists():
        entradas += ["-i", str(marca)]
        fil.append(f"[{prox}:v]scale=130:-1,format=rgba,colorchannelmixer=aa=0.85[m];[c1][m]overlay=W-w-28:40[c2]")
        prox += 1
    else:
        fil.append("[c1]null[c2]")
    # zoom bem leve em foto/texto pra não ficar parado
    if not video:
        fil.append(f"[c2]zoompan=z='min(1+0.0006*on,1.06)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                   f"s={W}x{H}:fps=30[c3]")
    else:
        fil.append("[c2]null[c3]")
    barra = "0x" + M.hexa(M.AZUL).lstrip("#")
    fil.append(f"[c3]ass='{editar._escapar(legenda)}':fontsdir='{editar._escapar(editar.FONTES)}',"
               f"drawbox=x=0:y=0:w='iw*t/{dur:.2f}':h=12:color={barra}@1:t=fill,format=yuv420p[v]")
    mapa_a = []
    if video:
        mapa_a = ["-map", "0:a?"]
    elif audio:
        entradas += ["-i", str(audio)]
        mapa_a = ["-map", f"{prox}:a"]
    else:  # Short mudo é ruim de distribuir: põe um silêncio limpo pelo menos
        entradas += ["-f", "lavfi", "-t", f"{dur:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
        mapa_a = ["-map", f"{prox}:a"]
    final = pasta / f"{post['id']}.mp4"
    editar.rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", ";".join(fil),
                  "-map", "[v]", *mapa_a, "-t", f"{dur:.2f}", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
                  "-movflags", "+faststart", str(final)])
    return final
