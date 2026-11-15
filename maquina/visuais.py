"""Os "olhos" do editor: o que aparece na tela em cada cena de um vídeo longo, além do trailer.

Tipos de visual (campo "visual" da cena no roteiro):
  trailer   imagens dos trailers oficiais (padrão)
  foto      foto real com licença livre (Wikimedia Commons), com movimento lento   {"busca": "..."}
  broll     vídeo real com licença livre (Wikimedia Commons); sem vídeo, cai pra foto  {"busca": "..."}
  mapa      mapa da Flórida desenhado na identidade Vice, com pinos  {"pinos": [{"nome","lat","lon"}], "titulo"}
  comparar  tela dividida: GTA 6 (trailer) x VIDA REAL (foto)  {"busca": "...", "rotulos": ["GTA 6", "VIDA REAL"]}
  manchete  ilustração de notícia feita por nós (nada de print de jornal)  {"data","local","titulo"} + fundo
Regra: nada de vídeo viral ou reportagem de terceiros (dá Content ID). Só licença livre, com crédito na descrição.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import marca as M
from .config import FONTES
from .editar import rodar

W, H, FPS = 1920, 1080, 30
UA = {"User-Agent": "CorteCityBot/1.0 (https://github.com/amiraldopedro/corte-city-maquina; YouTube channel bot)"}
API = "https://commons.wikimedia.org/w/api.php"
LICENCAS_OK = re.compile(r"^(cc0|public domain|pd|cc by(-sa)?( \d\.\d)?|cc-by(-sa)?-\d\.\d)", re.I)
ESTADOS = "https://raw.githubusercontent.com/PublicaMundi/MappingAPI/master/data/geojson/us-states.json"


def _f(nome: str, tam: int):
    return ImageFont.truetype(str(FONTES / nome), tam)


def _limpo(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()[:80]


# ---------------------------------------------------------------- Wikimedia Commons
def commons(busca: str, pasta: Path, video: bool = False, usados: set | None = None) -> tuple[Path, str] | None:
    """Procura uma foto (ou vídeo) com licença livre. Devolve (arquivo, crédito) ou None."""
    usados = usados if usados is not None else set()
    filtro = "filetype:video" if video else "filetype:bitmap"
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
              "gsrsearch": f"{busca} {filtro}", "gsrlimit": 15, "prop": "imageinfo|videoinfo",
              "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 1920,  # largura padrão: vem pronta do cache (thumb.wikimedia.org)
              "viprop": "url|derivatives|extmetadata|size|mime"}
    r = {}
    for tentativa in range(4):  # a Wikimedia limita pedidos seguidos: espera e tenta de novo
        try:
            resp = requests.get(API, params=params, headers=UA, timeout=30)
            if resp.status_code == 429 or "maxlag" in resp.text[:200]:
                time.sleep(5 * (tentativa + 1))
                continue
            r = resp.json()
            break
        except Exception as e:
            print(f"    commons: busca falhou ({str(e)[:80]})")
            time.sleep(3)
    paginas = sorted((r.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for p in paginas:
        info = ((p.get("videoinfo") or p.get("imageinfo")) or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = _limpo((meta.get("LicenseShortName") or {}).get("value", ""))
        if not LICENCAS_OK.match(lic) or p["title"] in usados:
            continue
        if video:
            ders = [d for d in info.get("derivatives", []) if "webm" in d.get("type", "") or d.get("src", "").endswith(".webm")]
            ders.sort(key=lambda d: abs(int(d.get("height", 0) or 0) - 720))
            url = ders[0]["src"] if ders else info.get("url")
            if not url or (info.get("size", 0) or 0) > 400e6:
                continue
        else:
            if (info.get("width") or 0) < 900:
                continue
            # o original (upload.wikimedia.org) devolve 429 para servidores do GitHub;
            # a miniatura em largura padrão vem do cache e passa sem problema
            url = info.get("thumburl") or info.get("url")
        ext = Path(url.split("?")[0]).suffix or (".webm" if video else ".jpg")
        destino = pasta / (hashlib.md5(url.encode()).hexdigest()[:12] + ext)
        baixou = destino.exists()
        for tentativa in range(4 if not video else 2):
            if baixou:
                break
            try:
                with requests.get(url, headers=UA, timeout=120, stream=True) as d:
                    if d.status_code == 429:
                        if "upload.wikimedia.org" in url:
                            break  # bloqueio do servidor de originais: não adianta insistir
                        time.sleep(6 * (tentativa + 1))
                        continue
                    d.raise_for_status()
                    with open(destino, "wb") as f:
                        for parte in d.iter_content(1 << 20):
                            f.write(parte)
                baixou = True
            except Exception as e:
                print(f"    commons: download falhou ({str(e)[:80]})")
                time.sleep(3)
        if not baixou:
            continue
        time.sleep(1)  # educação com o servidor
        if not video and destino.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"):
            try:
                im = Image.open(destino)
                if im.width > 2600:
                    im.convert("RGB").resize((2600, int(im.height * 2600 / im.width))).save(destino.with_suffix(".jpg"), quality=90)
                    destino = destino.with_suffix(".jpg")
            except Exception:
                continue
        autor = _limpo((meta.get("Artist") or {}).get("value", "")) or "autor desconhecido"
        usados.add(p["title"])
        nome = p["title"].replace("File:", "").replace("Arquivo:", "")
        return destino, f"{nome} — {autor} ({lic}), via Wikimedia Commons"
    return None if video else openverse(busca, pasta, usados)


def openverse(busca: str, pasta: Path, usados: set | None = None) -> tuple[Path, str] | None:
    """Reserva das fotos: Openverse (Flickr e outros acervos com licença livre que permite uso comercial)."""
    usados = usados if usados is not None else set()
    try:
        r = requests.get("https://api.openverse.org/v1/images/", timeout=30, headers=UA,
                         params={"q": busca, "license_type": "commercial,modification", "page_size": 12,
                                 "aspect_ratio": "wide,square"}).json()
    except Exception as e:
        print(f"    openverse: busca falhou ({str(e)[:80]})")
        return None
    for it in r.get("results", []):
        if it["id"] in usados or (it.get("width") or 0) < 900:
            continue
        destino = pasta / f"ov_{it['id'][:12]}.jpg"
        for url in (it.get("url"), f"https://api.openverse.org/v1/images/{it['id']}/thumb/?full_size=true"):
            try:
                d = requests.get(url, timeout=60)
                if d.ok and d.headers.get("content-type", "").startswith("image"):
                    destino.write_bytes(d.content)
                    Image.open(destino).convert("RGB").save(destino, quality=90)
                    break
            except Exception:
                continue
        else:
            continue
        usados.add(it["id"])
        lic = f"CC {it.get('license', '').upper()} {it.get('license_version') or ''}".strip()
        if it.get("license") in ("cc0", "pdm"):
            lic = "domínio público" if it["license"] == "pdm" else "CC0"
        return destino, f"{(it.get('title') or 'foto')[:60]} — {it.get('creator') or 'autor desconhecido'} ({lic}), via {it.get('source', 'Openverse')}"
    return None


# ---------------------------------------------------------------- foto com movimento
def foto_em_video(img: Path, dur: float, destino: Path, sentido: int = 1) -> Path:
    """Foto em 16:9 sem distorcer: fundo borrado + foto inteira por cima, com zoom lento (Ken Burns)."""
    base = Image.open(img).convert("RGB")
    fundo = base.resize((W, H)).filter(ImageFilter.GaussianBlur(40))
    fundo = Image.blend(fundo, Image.new("RGB", (W, H), M.NOITE), 0.45)
    escala = min(W * 0.92 / base.width, H * 0.92 / base.height)
    peq = base.resize((int(base.width * escala), int(base.height * escala)))
    fundo.paste(peq, ((W - peq.width) // 2, (H - peq.height) // 2))
    quadro = destino.with_suffix(".png")
    fundo.save(quadro)
    n = int(dur * FPS) + 1
    z = "1+0.08*on/%d" % n if sentido > 0 else "1.08-0.08*on/%d" % n
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(quadro), "-vf",
           f"scale=3840:-2,zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS}",
           "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(destino)])
    return destino


def video_em_video(src: Path, dur: float, destino: Path) -> Path:
    """Vídeo real (B-roll) em 16:9, em loop se for curto."""
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(src), "-t", f"{dur:.2f}", "-an",
           "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(destino)])
    return destino


# ---------------------------------------------------------------- mapa
def _contornos(pasta: Path) -> dict:
    cache = pasta / "estados.json"
    if not cache.exists():
        cache.write_bytes(requests.get(ESTADOS, timeout=30).content)
    d = json.loads(cache.read_text())
    return {f["properties"]["name"]: f["geometry"] for f in d["features"]}


def mapa(pinos: list[dict], titulo: str, pasta: Path, dur: float, destino: Path) -> Path:
    """Mapa da Flórida desenhado na identidade (noite, contorno azul neon, pinos rosa) com zoom no pino."""
    geo = _contornos(pasta)
    lon0, lon1, lat0, lat1 = -88.2, -79.2, 24.2, 31.4  # Flórida + começo da Geórgia/Alabama
    esc = min((W - 300) / (lon1 - lon0), (H - 160) / ((lat1 - lat0) * 1.12))

    def xy(lon, lat):
        return (150 + (lon - lon0) * esc, H - 60 - (lat - lat0) * esc * 1.12)

    img = Image.new("RGB", (W * 2, H * 2), M.NOITE)
    big = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    for x in range(0, W, 80):  # grade
        d.line([(x, 0), (x, H)], fill=(31, 184, 255, 22))
    for y in range(0, H, 80):
        d.line([(0, y), (W, y)], fill=(31, 184, 255, 22))
    for nome in ("Alabama", "Georgia", "Florida"):
        g = geo.get(nome)
        if not g:
            continue
        polis = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poli in polis:
            pts = [xy(lo, la) for lo, la in poli[0]]
            cheio = (*M.OCEANO, 255) if nome == "Florida" else (19, 25, 60, 255)
            d.polygon(pts, fill=cheio, outline=(*M.AZUL, 255) if nome == "Florida" else (60, 80, 140, 255))
    brilho = big.filter(ImageFilter.GaussianBlur(8))
    camada = Image.alpha_composite(brilho, big)
    d = ImageDraw.Draw(camada)
    f_nome, f_tit = _f("Inter-ExtraBold.ttf", 36), _f("Anton-Regular.ttf", 72)
    for p in pinos:
        x, y = xy(p["lon"], p["lat"])
        for r, a in ((34, 60), (22, 120)):
            d.ellipse([x - r, y - r, x + r, y + r], fill=(*M.ROSA, a))
        d.ellipse([x - 11, y - 11, x + 11, y + 11], fill=(*M.ROSA, 255), outline=(*M.AREIA, 255), width=3)
        lw = int(f_nome.getlength(p["nome"])) + 36
        lx = x + 30 if x < W - lw - 60 else x - 30 - lw
        d.rounded_rectangle([lx, y - 30, lx + lw, y + 30], 12, fill=(*M.NOITE, 235), outline=(*M.ROSA, 255), width=3)
        d.text((lx + 18, y), p["nome"], font=f_nome, fill=M.AREIA, anchor="lm")
    tit_png = destino.with_name(destino.stem + "_tit.png")
    tit = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if titulo:  # o título fica parado por cima (não entra no zoom)
        dt = ImageDraw.Draw(tit)
        dt.text((80, 60), titulo.upper(), font=f_tit, fill=M.AREIA, stroke_width=4, stroke_fill=M.NOITE)
        dt.line([(80, 158), (80 + int(f_tit.getlength(titulo.upper())), 158)], fill=(*M.ROSA, 255), width=6)
    tit.save(tit_png)
    img = Image.new("RGB", (W, H), M.NOITE)
    img.paste(camada, (0, 0), camada)
    quadro = destino.with_suffix(".png")
    img.save(quadro)
    # zoom lento em direção ao primeiro pino
    px, py = xy(pinos[0]["lon"], pinos[0]["lat"]) if pinos else (W / 2, H / 2)
    n = int(dur * FPS) + 1
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(quadro), "-loop", "1", "-i", str(tit_png),
           "-filter_complex",
           f"[0:v]scale=3840:-2,zoompan=z='1+0.18*on/{n}':x='{px * 2:.0f}-(iw/zoom/2)':y='{py * 2:.0f}-(ih/zoom/2)'"
           f":d={n}:s={W}x{H}:fps={FPS}[m];[m][1:v]overlay=0:0,format=yuv420p[v]", "-map", "[v]",
           "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(destino)])
    return destino


# ---------------------------------------------------------------- manchete ilustrada
def manchete(c: dict, destino: Path) -> tuple[Path, int, int]:
    """Card de notícia feito por nós: data e lugar numa etiqueta rosa, a manchete em Anton, carimbo 'VIDA REAL'."""
    larg = 1180
    f_tag, f_tit, f_car = _f("Inter-ExtraBold.ttf", 34), _f("Anton-Regular.ttf", 78), _f("Anton-Regular.ttf", 40)
    import textwrap
    linhas = textwrap.wrap(c.get("titulo", ""), 26)[:3]
    alto = 150 + 92 * len(linhas) + 60
    img = Image.new("RGBA", (larg + 24, alto + 24), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([24, 24, larg + 23, alto + 23], fill=(*M.AMEIXA, 255))  # sombra dura
    d.rectangle([0, 0, larg - 1, alto - 1], fill=(*M.AREIA, 255))
    tag = f"{c.get('data', '')} · {c.get('local', '')}".strip(" ·").upper()
    tw = int(f_tag.getlength(tag)) + 40
    d.rectangle([40, 40, 40 + tw, 100], fill=(*M.ROSA, 255))
    d.text((60, 70), tag, font=f_tag, fill=M.NOITE, anchor="lm")
    y = 135
    for ln in linhas:
        d.text((40, y), ln.upper(), font=f_tit, fill=M.NOITE)
        y += 92
    carimbo = "VIDA REAL"
    cw = int(f_car.getlength(carimbo)) + 36
    d.rectangle([larg - cw - 40, 40, larg - 40, 100], outline=(*M.AZUL, 255), width=4)
    d.text((larg - cw // 2 - 40, 70), carimbo, font=f_car, fill=M.AZUL, anchor="mm")
    img.save(destino)
    return destino, (W - img.width) // 2, max(120, (H - img.height) // 2 - 80)


# ---------------------------------------------------------------- comparação lado a lado
def comparar(trailer: Path, ini: float, foto: Path, dur: float, rotulos: list[str], destino: Path) -> Path:
    """Tela dividida: à esquerda o trailer (GTA 6), à direita a foto real, com rótulos e divisória rosa."""
    meia = W // 2
    base = Image.open(foto).convert("RGB")
    esc = max(meia / base.width, H / base.height)
    base = base.resize((int(base.width * esc) + 1, int(base.height * esc) + 1))
    x0, y0 = (base.width - meia) // 2, (base.height - H) // 2
    lado = base.crop((x0, y0, x0 + meia, y0 + H))
    lado_png = destino.with_name(destino.stem + "_real.png")
    lado.save(lado_png)
    rot = destino.with_name(destino.stem + "_rot.png")
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([meia - 4, 0, meia + 4, H], fill=(*M.ROSA, 255))
    f = _f("Anton-Regular.ttf", 56)
    for i, texto in enumerate(rotulos[:2]):
        tw = int(f.getlength(texto)) + 44
        x = 40 if i == 0 else meia + 40
        cor = M.AZUL if i == 0 else M.ROSA
        d.rectangle([x, 50, x + tw, 130], fill=(*cor, 255))
        d.text((x + tw // 2, 90), texto, font=f, fill=M.NOITE, anchor="mm")
    img.save(rot)
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{ini:.2f}", "-t", f"{dur:.2f}", "-i", str(trailer),
           "-loop", "1", "-t", f"{dur:.2f}", "-i", str(lado_png), "-loop", "1", "-t", f"{dur:.2f}", "-i", str(rot),
           "-filter_complex",
           f"[0:v]scale=-2:{H},crop={meia}:{H},setsar=1,fps={FPS}[a];[1:v]scale={meia}:{H},setsar=1,fps={FPS},"
           f"zoompan=z='1+0.05*on/{int(dur * FPS) + 1}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={meia}x{H}:fps={FPS}[b];"
           f"[a][b]hstack[c];[c][2:v]overlay=0:0,format=yuv420p[v]",
           "-map", "[v]", "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(destino)])
    return destino
