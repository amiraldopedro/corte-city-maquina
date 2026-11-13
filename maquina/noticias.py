"""Shorts de notícia do GTA 6, a partir do Google Notícias e de posts do X que você colar.

Tudo grátis:
- Google Notícias: feed RSS público, busca por "GTA 6".
- Posts do X: o oEmbed oficial do X (publish.twitter.com) lê um post pelo link, sem chave.
- Narração: edge-tts (vozes neurais em português).
- Fundo: um clipe de GTA da Twitch, sem o som.

Segurança: vazamento, conteúdo adulto e coisas sensíveis são barrados duas vezes
(lista de palavras + a IA julgando). A IA reescreve com as próprias palavras e dá o crédito da fonte.
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import re
import textwrap
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from .config import FONTES

UA = {"User-Agent": "CorteCityBot/1.0 (+https://youtube.com/@cortecity)"}

# vazamento / adulto / sensível: some na hora, nem chega na IA
BLOQUEIO = re.compile(
    r"vaza|vazou|vazad|leak|datamin|insider|build interna|código fonte|source code|hack|"
    r"nsfw|porn|nud[eo]|sexo|sexual|onlyfans|\+18|18\+|nazi|suic|estupr|pedof|"
    r"morte de|morreu|assassin|tiroteio real|atentado",
    re.I)

VOZES = {"pt": "pt-BR-AntonioNeural", "en": "en-US-GuyNeural"}


def _id(texto: str) -> str:
    return "news_" + hashlib.sha1(texto.encode()).hexdigest()[:12]


def bloqueado(*textos: str) -> bool:
    return bool(BLOQUEIO.search(" ".join(t or "" for t in textos)))


# ------------------------------------------------------------------ fontes
def google_noticias(termos: list[str], idioma: str = "pt", horas: int = 30) -> list[dict]:
    hl, gl, ceid = ("pt-BR", "BR", "BR:pt-419") if idioma == "pt" else ("en-US", "US", "US:en")
    limite = datetime.now(timezone.utc) - timedelta(hours=horas)
    vistos, saida = set(), []
    for termo in termos:
        r = requests.get("https://news.google.com/rss/search", headers=UA, timeout=30,
                         params={"q": f'"{termo}" when:2d', "hl": hl, "gl": gl, "ceid": ceid})
        r.raise_for_status()
        for item in ET.fromstring(r.content).iter("item"):
            titulo = html.unescape(item.findtext("title") or "")
            fonte = item.findtext("source") or ""
            if fonte and titulo.endswith(" - " + fonte):
                titulo = titulo[: -len(fonte) - 3]
            try:
                quando = parsedate_to_datetime(item.findtext("pubDate"))
            except Exception:
                continue
            chave = re.sub(r"\W", "", titulo.lower())[:60]
            if quando < limite or chave in vistos:
                continue
            vistos.add(chave)
            saida.append({"id": _id(chave), "origem": "noticia", "titulo_fonte": titulo, "fonte": fonte,
                          "link": item.findtext("link") or "", "publicado": quando.isoformat()})
    return saida


def post_do_x(link: str) -> dict:
    """Lê um post público do X pelo link (oEmbed oficial, sem chave)."""
    link = link.strip().replace("x.com/", "twitter.com/")
    r = requests.get("https://publish.twitter.com/oembed", headers=UA, timeout=30,
                     params={"url": link, "omit_script": "1", "dnt": "true"})
    r.raise_for_status()
    d = r.json()
    corpo = re.search(r"<p[^>]*>(.*?)</p>", d.get("html", ""), re.S)
    texto = html.unescape(re.sub(r"<[^>]+>", " ", corpo.group(1) if corpo else "")).strip()
    texto = re.sub(r"\s+", " ", re.sub(r"pic\.twitter\.com/\S+|https?://t\.co/\S+", "", texto)).strip()
    autor = d.get("author_name", "")
    perfil = d.get("author_url", "").rstrip("/").split("/")[-1]
    return {"id": _id(link), "origem": "x", "titulo_fonte": texto, "fonte": f"{autor} (@{perfil})",
            "autor": autor, "perfil": perfil, "link": link.replace("twitter.com/", "x.com/")}


# ------------------------------------------------------------------ roteiro (IA)
PROMPT = """Você roteiriza Shorts de NOTÍCIA sobre GTA 6 para o canal brasileiro {canal}.
Fonte: {fonte}
Texto original: "{texto}"

Classifique em "categoria" (escolha UMA):
- "ok": notícia normal sobre GTA (lançamento, preço, consoles, pré-venda, recordes, streamers, trailers, curiosidades). A grande maioria é "ok".
- "adulto": conteúdo sexual explícito.
- "violencia_real": crime ou morte de pessoas reais.
- "fora": não tem nada a ver com GTA.
Na dúvida, use "ok". Se for rumor, só deixe claro na narração que é rumor.

Depois escreva em {idioma_nome}, com as SUAS palavras (não copie frases do original):
- "narracao": 50 a 75 palavras, em português do Brasil correto e natural, como um apresentador animado de canal de games. Comece pelo fato mais forte já na primeira frase (sem "oi pessoal", sem "oie"). Não cite nome de site ou jornal, não invente números nem detalhes que não estão no texto. Termine com uma pergunta pra gerar comentário (ex.: "E aí, vai comprar no dia?").
- "titulo": 45 a 65 caracteres, "GTA 6" no começo, sem mentir, sem hashtag.
- "chamada": 3 a 5 palavras para a tela nos primeiros segundos (ex.: "A ROCKSTAR CONFIRMOU").
- "manchete": até 9 palavras, resumo do fato para o cartão na tela.
- "tags": 8 a 12 buscas do YouTube.

Responda só com JSON: {{"categoria": "ok", "narracao": "...", "titulo": "...", "chamada": "...", "manchete": "...", "tags": ["..."]}}"""


def roteiro(item: dict, canal: str, idioma: str, perguntar) -> dict | None:
    from .cerebro import IDIOMAS, _limpar_titulo
    r = perguntar(PROMPT.format(canal=canal, fonte=item["fonte"], texto=item["titulo_fonte"][:900],
                                idioma_nome=IDIOMAS[idioma]))
    categoria = str(r.get("categoria", "ok")).lower().strip()
    if categoria in ("adulto", "violencia_real", "fora") or bloqueado(r.get("narracao", ""), r.get("titulo", "")):
        print(f"  notícia barrada: {item['titulo_fonte'][:80]} ({categoria})")
        return None
    narracao = re.sub(r"\s+", " ", str(r.get("narracao", ""))).strip()
    titulo = _limpar_titulo(str(r.get("titulo", "")))
    if len(narracao.split()) < 25 or "gta" not in (titulo + narracao).lower():
        return None
    return {"narracao": narracao, "titulo": titulo if len(titulo) >= 20 else f"GTA 6: {item['titulo_fonte'][:55]}",
            "chamada": str(r.get("chamada", "")).upper()[:36] or "NOVIDADE DO GTA 6",
            "manchete": str(r.get("manchete", ""))[:80] or item["titulo_fonte"][:80],
            "tags": [str(t).lower()[:40] for t in (r.get("tags") or [])][:12]}


# ------------------------------------------------------------------ voz
async def _falar(texto: str, voz: str, destino: Path, taxa: str = "+8%") -> list[dict]:
    import edge_tts
    palavras = []
    com = edge_tts.Communicate(texto, voz, rate=taxa, boundary="WordBoundary")
    with open(destino, "wb") as f:
        async for pedaco in com.stream():
            if pedaco["type"] == "audio":
                f.write(pedaco["data"])
            elif pedaco["type"] == "WordBoundary":
                i = pedaco["offset"] / 1e7
                palavras.append({"p": pedaco["text"], "i": i, "f": i + pedaco["duration"] / 1e7})
    return palavras


def narrar(texto: str, idioma: str, destino: Path) -> list[dict]:
    """Gera o MP3 da narração e devolve as palavras com tempo (para a legenda)."""
    return asyncio.run(_falar(texto, VOZES[idioma], destino))


# ------------------------------------------------------------------ cartão
def cartao(item: dict, manchete: str, cor: str, destino: Path, idioma: str) -> Path:
    """Cartão estilo post: quem disse / de onde veio + a manchete."""
    W = 960
    fonte_b = ImageFont.truetype(str(FONTES / "Inter-ExtraBold.ttf"), 58)
    fonte_s = ImageFont.truetype(str(FONTES / "Inter-SemiBold.ttf"), 34)
    linhas = textwrap.wrap(manchete, 24)[:4]
    alto = 150 + 74 * len(linhas) + 70
    img = Image.new("RGBA", (W, alto), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, alto - 1], 36, fill=(14, 14, 18, 235), outline=cor, width=6)
    rotulo = ("POST NO X" if item["origem"] == "x" else "NOTÍCIA") if idioma == "pt" else \
             ("POST ON X" if item["origem"] == "x" else "NEWS")
    d.rounded_rectangle([40, 40, 40 + 30 + int(fonte_s.getlength(rotulo)), 96], 14, fill=cor)
    d.text((55, 46), rotulo, font=fonte_s, fill=(10, 10, 10))
    d.text((40, 110), item["fonte"][:42], font=fonte_s, fill=(190, 190, 200))
    y = 170
    for ln in linhas:
        d.text((40, y), ln, font=fonte_b, fill=(255, 255, 255))
        y += 74
    img.save(destino)
    return destino
