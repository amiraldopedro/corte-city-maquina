"""Vídeo longo narrado (16:9): roteiro em cenas -> voz + imagens de fundo + cards animados + legenda.

Entrega nos downloads do painel (Releases) com títulos, descrição com capítulos, tags e kit de thumb.
NÃO posta no YouTube: quem posta é você.

Imagens de fundo: a "biblioteca" (vídeos inteiros que o robô do Mac sobe, ex.: trailers oficiais).
Sem biblioteca, usa clipes de GTA bem vistos da Twitch.
"""
from __future__ import annotations

import asyncio
import json
import random
import textwrap
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import marca as M
from .config import FONTES, PASTA_PRONTOS
from .editar import _escapar, info_video, rodar

W, H, FPS = 1920, 1080, 30
TAG_BIBLIOTECA = "biblioteca"
PAUSA = 0.45  # respiro entre cenas


def _fonte(nome: str, tam: int):
    return ImageFont.truetype(str(FONTES / nome), tam)


def _rgb(cor: str) -> tuple[int, int, int]:
    cor = cor.lstrip("#")
    return tuple(int(cor[i:i + 2], 16) for i in (0, 2, 4))


# ------------------------------------------------------------------ cards
def card(c: dict, cor: str, destino: Path) -> tuple[Path, int, int] | None:
    """PNG transparente do card + posição (x, y) onde ele entra."""
    tipo = c.get("tipo", "nenhum")
    if tipo == "nenhum":
        return None
    ac = _rgb(cor)
    escuro = (*M.NOITE, 232)
    if tipo == "titulo":
        f1, f2 = _fonte("Anton-Regular.ttf", 190), _fonte("Inter-ExtraBold.ttf", 54)
        t, sub = c.get("texto", "").upper(), c.get("sub", "")
        lw = max(int(f1.getlength(t)), int(f2.getlength(sub))) + 160
        img = Image.new("RGBA", (lw, 380), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, lw - 1, 379], 36, fill=escuro)
        d.rectangle([0, 0, 18, 379], fill=ac + (255,))
        d.text((lw // 2, 150), t, font=f1, fill=M.AREIA, anchor="mm")
        d.text((lw // 2, 300), sub, font=f2, fill=ac, anchor="mm")
        img.save(destino)
        return destino, (W - lw) // 2, (H - 380) // 2 - 60
    if tipo == "dado":
        f1, f2 = _fonte("Anton-Regular.ttf", 170), _fonte("Inter-ExtraBold.ttf", 46)
        num, txt = str(c.get("numero", "")), c.get("texto", "")
        linhas = textwrap.wrap(txt, 26)[:3]
        lw = max(int(f1.getlength(num)), max((int(f2.getlength(l)) for l in linhas), default=0)) + 140
        alto = 240 + 60 * len(linhas) + 40
        img = Image.new("RGBA", (lw, alto), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, lw - 1, alto - 1], 32, fill=escuro)
        d.rectangle([0, 0, 16, alto - 1], fill=ac + (255,))
        d.text((70, 30), num, font=f1, fill=ac)
        y = 240
        for l in linhas:
            d.text((70, y), l, font=f2, fill=M.AREIA); y += 60
        img.save(destino)
        return destino, 110, (H - alto) // 2 - 80
    if tipo == "lista":
        itens = c.get("itens", [])[:6]
        f = _fonte("Inter-ExtraBold.ttf", 48)
        lw = max(int(f.getlength(i)) for i in itens) + 200
        alto = 60 + 92 * len(itens) + 30
        img = Image.new("RGBA", (lw, alto), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, lw - 1, alto - 1], 32, fill=escuro)
        y = 50
        for n, it in enumerate(itens, 1):
            d.ellipse([50, y + 4, 110, y + 64], fill=ac + (255,))
            d.text((80, y + 34), str(n), font=_fonte("Anton-Regular.ttf", 42), fill=M.NOITE, anchor="mm")
            d.text((135, y + 8), it, font=f, fill=M.AREIA)
            y += 92
        img.save(destino)
        return destino, W - lw - 110, (H - alto) // 2 - 80
    if tipo == "numero":
        f1, f2 = _fonte("Anton-Regular.ttf", 200), _fonte("Inter-ExtraBold.ttf", 58)
        linhas = textwrap.wrap(c.get("texto", ""), 22)[:3]
        lw = max([int(f2.getlength(l)) for l in linhas] + [300]) + 420
        alto = max(330, 70 * len(linhas) + 140)
        img = Image.new("RGBA", (lw, alto), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, lw - 1, alto - 1], 36, fill=escuro)
        d.ellipse([50, alto // 2 - 120, 290, alto // 2 + 120], fill=ac + (255,))
        d.text((170, alto // 2 + 6), str(c.get("numero", "")), font=f1, fill=M.NOITE, anchor="mm")
        y = alto // 2 - 35 * len(linhas)
        for l in linhas:
            d.text((340, y), l, font=f2, fill=M.AREIA); y += 70
        img.save(destino)
        return destino, (W - lw) // 2, (H - alto) // 2 - 80
    return None


# ------------------------------------------------------------------ legenda e capítulo
def _t(s: float) -> str:
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"


def legenda(palavras: list[dict], capitulo: str, cor: str, destino: Path) -> Path:
    r, g, b = _rgb(cor)
    linhas = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
              "[V4+ Styles]",
              "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
              "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
              "MarginR, MarginV, Encoding",
              "Style: L,Inter ExtraBold,54,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,5,2,2,160,160,70,1",
              f"Style: C,Anton,62,&H00FFFFFF,&H00FFFFFF,&H00{b:02X}{g:02X}{r:02X},&H00{b:02X}{g:02X}{r:02X},0,0,0,0,100,100,1,0,3,18,0,7,80,80,60,1",
              "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    if capitulo:
        linhas.append(f"Dialogue: 1,{_t(0.1)},{_t(3.4)},C,,0,0,0,,{{\\fad(200,300)}}{capitulo.upper()}")
    bloco: list[dict] = []
    for i, p in enumerate(palavras):
        bloco.append(p)
        fim_frase = p["p"].rstrip().endswith((".", "!", "?", ","))
        if len(bloco) >= 8 or (fim_frase and len(bloco) >= 4) or i == len(palavras) - 1:
            txt = " ".join(x["p"] for x in bloco).replace("{", "").replace("}", "")
            fim = palavras[i + 1]["i"] if i + 1 < len(palavras) else bloco[-1]["f"] + 0.3
            linhas.append(f"Dialogue: 0,{_t(bloco[0]['i'])},{_t(fim)},L,,0,0,0,,{txt}")
            bloco = []
    destino.write_text("\n".join(linhas), encoding="utf-8")
    return destino


# ------------------------------------------------------------------ voz
def falar(texto: str, voz: str, taxa: str, destino: Path) -> list[dict]:
    """O serviço de voz grátis às vezes para de responder depois de muitos pedidos: espera e tenta de novo."""
    import time
    from .noticias import _falar
    espera = 5
    for tentativa in range(7):
        try:
            palavras = asyncio.run(_falar(texto, voz, destino, taxa))
            if palavras:
                time.sleep(1.0)  # respiro entre cenas pra não ser barrado
                return palavras
            raise RuntimeError("voz sem palavras")
        except Exception as e:
            if tentativa == 6:
                raise
            print(f"  voz não respondeu ({str(e)[:60]}), tentando de novo em {espera}s")
            time.sleep(espera)
            espera = min(espera * 2, 90)


# ------------------------------------------------------------------ imagens de fundo
class Fundos:
    """Sorteia trechos das fontes sem repetir o mesmo pedaço."""

    def __init__(self, arquivos: list[Path], semente: int = 7):
        self.fontes = [(a, info_video(a)[2]) for a in arquivos]
        self.fontes = [(a, d) for a, d in self.fontes if d >= 4]
        if not self.fontes:
            raise RuntimeError("nenhuma imagem de fundo disponível")
        self.usado: dict[Path, list[tuple[float, float]]] = {a: [] for a, _ in self.fontes}
        self.rng = random.Random(semente)
        self.vez = 0

    def trecho(self, dur: float) -> tuple[Path, float]:
        for _ in range(40):
            a, total = self.fontes[self.vez % len(self.fontes)]
            self.vez += 1
            if total <= dur + 1:
                return a, 0.0
            lo, hi = (18.0, total - 14.0) if total > dur + 40 else (0.5, total - 0.5)  # pula ESRB/logos
            ini = self.rng.uniform(lo, max(lo + 0.1, hi - dur))
            if all(ini + dur < x or ini > y for x, y in self.usado[a]):
                self.usado[a].append((ini, ini + dur))
                return a, ini
        a, total = self.rng.choice(self.fontes)
        return a, max(0.0, self.rng.uniform(0, max(0.1, total - dur)))


    def por_nome(self, nome: str) -> Path | None:
        return next((a for a, _ in self.fontes if nome and nome in a.name), None)


def _repo_arquivos():
    import os
    if not os.environ.get("GITHUB_REPOSITORY"):
        return None, None
    from . import arquivos
    return arquivos.repo(), arquivos.token()


def fontes_citadas(pasta: Path, prefixo: str) -> dict[str, Path]:
    """Trechos de vídeos de terceiros que o robô do Mac subiu (Releases, tag fontes)."""
    import os
    repo, token = _repo_arquivos()
    if not (repo and token):
        return {p.stem: p for p in pasta.glob(f"{prefixo}*.mp4")} if pasta.exists() else {}
    cab = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"https://api.github.com/repos/{repo}/releases/tags/fontes", headers=cab, timeout=30)
    saida = {}
    if r.status_code != 200:
        return saida
    pasta.mkdir(parents=True, exist_ok=True)
    for a in r.json().get("assets", []):
        if not (a["name"].startswith(prefixo) and a["name"].endswith(".mp4")):
            continue
        destino = pasta / a["name"]
        if not destino.exists():
            d = requests.get(a["url"], headers={**cab, "Accept": "application/octet-stream"}, timeout=600)
            d.raise_for_status()
            destino.write_bytes(d.content)
        saida[destino.stem] = destino
    return saida


_OFICIAIS: list | None = None


def oficial_por_nome(nome: str, pasta: Path) -> Path | None:
    """Screenshot oficial da Rockstar (Releases, tag oficiais), baixada só quando usada. Ex.: 'Vice_City_05'."""
    import os
    global _OFICIAIS
    repo, token = _repo_arquivos()
    pasta.mkdir(parents=True, exist_ok=True)
    local = [p for p in pasta.glob("of_*") if f"_{nome}." in p.name]
    if local:
        return local[0]
    if not (repo and token and nome):
        return None
    cab = {"Authorization": f"Bearer {token}"}
    if _OFICIAIS is None:
        _OFICIAIS, pagina = [], 1
        while True:
            r = requests.get(f"https://api.github.com/repos/{repo}/releases/tags/oficiais", headers=cab, timeout=30)
            if r.status_code != 200:
                break
            rid = r.json()["id"]
            while True:
                a = requests.get(f"https://api.github.com/repos/{repo}/releases/{rid}/assets?per_page=100&page={pagina}",
                                 headers=cab, timeout=30).json()
                if not a:
                    break
                _OFICIAIS += a
                pagina += 1
            break
    alvo = next((a for a in _OFICIAIS if f"_{nome}." in a["name"]), None)
    if not alvo:
        return None
    d = requests.get(alvo["url"], headers={**cab, "Accept": "application/octet-stream"}, timeout=300)
    d.raise_for_status()
    destino = pasta / alvo["name"]
    destino.write_bytes(d.content)
    return destino


def _info_fonte(chave: str) -> dict:
    try:
        from .config import PASTA_ESTADO
        return json.loads((PASTA_ESTADO / "youtube.json").read_text()).get("momentos", {}).get(chave, {})
    except Exception:
        return {}


# cópia repetida do Extended Look (a usada é _OECwb8j9U4): não baixar
IGNORAR_BIBLIOTECA = {"bib_xHm_RF0WBCg.mp4"}


def biblioteca(pasta: Path) -> list[Path]:
    """Baixa os vídeos da biblioteca (Releases, tag biblioteca)."""
    import os
    repo, token = _repo_arquivos()
    if not (repo and token):
        return []
    cab = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"https://api.github.com/repos/{repo}/releases/tags/{TAG_BIBLIOTECA}", headers=cab, timeout=30)
    if r.status_code != 200:
        return []
    pasta.mkdir(parents=True, exist_ok=True)
    saida = []
    for a in r.json().get("assets", []):
        if not a["name"].endswith(".mp4") or a["name"] in IGNORAR_BIBLIOTECA:
            continue
        destino = pasta / a["name"]
        if not destino.exists():
            with requests.get(a["url"], headers={**cab, "Accept": "application/octet-stream"}, stream=True,
                              timeout=900) as d:
                d.raise_for_status()
                with open(destino, "wb") as f:
                    for pedaco in d.iter_content(1 << 20):
                        f.write(pedaco)
        saida.append(destino)
    return saida


# ------------------------------------------------------------------ montagem
def _fundo_visual(i: int, c: dict, dur: float, fundos: Fundos, pasta: Path, creditos: list, usados: set):
    """Monta o vídeo de fundo da cena conforme o "visual" pedido no roteiro. None = usar o trailer."""
    from . import visuais as V
    v = c.get("visual") or {}
    tipo = v.get("tipo", "trailer")
    if tipo == "trailer":
        return None, None
    cache = pasta / "midia"
    cache.mkdir(exist_ok=True)
    destino = pasta / f"c{i:02d}_fundo.mp4"
    try:
        if tipo == "mapa":
            return V.mapa(v.get("pinos", []), v.get("titulo", ""), cache, dur, destino), None
        if tipo in ("foto", "broll", "manchete", "comparar") and v.get("busca"):
            achado = None
            if tipo == "broll":
                achado = V.commons(v["busca"], cache, video=True, usados=usados)
                if achado:
                    creditos.append(achado[1])
                    return V.video_em_video(achado[0], dur, destino), None
            achado = V.commons(v["busca"], cache, usados=usados)
            if achado:
                creditos.append(achado[1])
                if tipo == "comparar":
                    src, ini = fundos.trecho(dur)
                    return V.comparar(src, ini, achado[0], dur, v.get("rotulos", ["GTA 6", "VIDA REAL"]), destino), None
                return V.foto_em_video(achado[0], dur, destino, 1 if i % 2 else -1), None
            print(f"  (cena {i + 1}: não achei imagem livre pra '{v['busca']}', vai o trailer)")
    except Exception as e:
        print(f"  (cena {i + 1}: visual '{tipo}' falhou, vai o trailer: {str(e)[:120]})")
    return None, None


def _batida(b: dict, k: int, i: int, dur: float, fundos: Fundos, pasta: Path, creditos: list, usados: set,
            citadas: dict) -> Path:
    """Um pedaço da cena (ver edicao.py)."""
    from . import edicao as E
    from . import visuais as V
    destino = pasta / f"c{i:02d}_b{k:02d}.mp4"
    tipo = b.get("tipo", "trailer")
    cache = pasta / "midia"
    cache.mkdir(exist_ok=True)
    if tipo == "clipe":
        src = citadas.get(b.get("fonte", ""))
        if not src:
            print(f"  (cena {i + 1}: trecho '{b.get('fonte')}' ainda não chegou, vai a reserva)")
            return _batida(b.get("reserva") or {"tipo": "trailer"}, k, i, dur, fundos, pasta, creditos, usados, citadas)
        info = _info_fonte(b["fonte"])
        cred = b.get("credito") or info.get("canal_nome") or "vídeo original"
        creditos.append(f"Trecho citado: \"{info.get('titulo', b['fonte'])}\" — {info.get('canal_nome', cred)}"
                        f" ({info.get('url_final') or info.get('link', '')})")
        return E.clipe(src, float(b.get("ini", 0)), dur, cred, destino, float(b.get("volume", 0.35)))
    if tipo == "materia":
        creditos.append(f"Matéria: {b.get('veiculo', '')}, {b.get('data', '')} — {b.get('url', '')}".strip(" —"))
        return E.materia(b, dur, cache, destino)
    if tipo == "numero":
        src = fundos.por_nome(b.get("arquivo", "")) if b.get("arquivo") else None
        if b.get("arquivo") and src:
            return E.numero(b, dur, destino, src, float(b.get("ini", 20)))
        src, ini = fundos.trecho(dur)
        return E.numero(b, dur, destino, src, ini)
    if tipo == "oficial":
        img = oficial_por_nome(b.get("arquivo", ""), pasta.parent / "oficiais")
        if img:
            creditos.append("Screenshots oficiais: Rockstar Games")
            foco = tuple(b.get("foco", (0.5, 0.5)))
            return E.oficial(img, dur, destino, foco, float(b.get("de", 1.0)), float(b.get("ate", 1.12)))
        print(f"  (imagem oficial '{b.get('arquivo')}' não achada, vai trailer)")
        tipo = "trailer"
    if tipo in ("capitulo", "procurado"):
        src = fundos.por_nome(b.get("arquivo", "")) if b.get("arquivo") else None
        ini = float(b.get("ini", 20))
        if src is None:
            src, ini = fundos.trecho(dur)
        return (E.capitulo if tipo == "capitulo" else E.procurado)(b, dur, destino, src, ini)
    if tipo == "comparar":
        esq = fundos.por_nome(b.get("arquivo", "")) or fundos.trecho(dur)[0]
        if b.get("fonte") and citadas.get(b["fonte"]):
            info = _info_fonte(b["fonte"])
            creditos.append(f"Trecho citado: \"{info.get('titulo', b['fonte'])}\" — {info.get('canal_nome', '')}"
                            f" ({info.get('url_final') or info.get('link', '')})")
            return E.comparar(esq, float(b.get("ini", 20)), citadas[b["fonte"]], float(b.get("fonte_ini", 0)), dur,
                              b.get("rotulos"), destino)
        achado = V.commons(b.get("busca", ""), cache, usados=usados) if b.get("busca") else None
        if achado:
            creditos.append(achado[1])
            return E.comparar(esq, float(b.get("ini", 20)), achado[0], 0, dur, b.get("rotulos"), destino, dir_e_foto=True)
        tipo = "trailer"
    if tipo in ("foto", "broll", "mapa"):
        bruto, _ = _fundo_visual(i * 100 + k, {"visual": b}, dur, fundos, pasta, creditos, usados)
        if bruto:
            return E.com_audio(bruto, dur, destino)
        tipo = "trailer"
    src = fundos.por_nome(b.get("arquivo", "")) if b.get("arquivo") else None
    rot = tuple(b["etiqueta"]) if b.get("etiqueta") else None
    if src is not None and "ini" in b:
        return E.trailer(src, float(b["ini"]), dur, destino, 1 if k % 2 == 0 else -1, rot)
    src, ini = fundos.trecho(dur)
    return E.trailer(src, ini, dur, destino, 1 if k % 2 == 0 else -1, rot)


def cena(i: int, c: dict, voz: str, taxa: str, fundos: Fundos, cor: str, marca: Path | None, pasta: Path,
         creditos: list | None = None, usados: set | None = None, citadas: dict | None = None) -> dict:
    creditos = creditos if creditos is not None else []
    usados = usados if usados is not None else set()
    audio = pasta / f"c{i:02d}.mp3"
    palavras = falar(c["texto"], voz, taxa, audio)
    dur = (palavras[-1]["f"] if palavras else 4) + PAUSA
    ass = legenda(palavras, c.get("capitulo", "") if i else "", cor, pasta / f"c{i:02d}.ass")
    v = c.get("visual") or {}
    if v.get("tipo") == "manchete":  # a ilustração da notícia toma o lugar do card
        from .visuais import manchete
        cd = manchete(v, pasta / f"c{i:02d}.png")
    else:
        cd = card(c.get("card", {}), cor, pasta / f"c{i:02d}.png")
    com_som = False
    if c.get("batidas"):
        from . import edicao as E
        pedacos = []
        for k, (b, (t0, t1)) in enumerate(zip(c["batidas"], E.tempos(c["batidas"], palavras, dur))):
            try:
                pedacos.append(_batida(b, k, i, t1 - t0, fundos, pasta, creditos, usados, citadas or {}))
            except Exception as e:
                print(f"  (cena {i + 1}, batida {k + 1} '{b.get('tipo')}' falhou: {str(e)[:160]}; vai trailer)")
                pedacos.append(_batida({"tipo": "trailer"}, k, i, t1 - t0, fundos, pasta, creditos, usados, {}))
        fundo, com_som = E.colar(pedacos, pasta / f"c{i:02d}_fundo.mp4"), True
    else:
        fundo, _ = _fundo_visual(i, c, dur, fundos, pasta, creditos, usados)
    if fundo:
        entradas = ["-i", str(fundo), "-i", str(audio)]
        escurece = "-0.18" if cd else ("0" if com_som else "-0.04")
        fil = [f"[0:v]scale={W}:{H},setsar=1,fps={FPS},eq=brightness={escurece}[b0]"]
    else:
        src, ini = fundos.trecho(dur)
        entradas = ["-ss", f"{ini:.2f}", "-t", f"{dur:.2f}", "-i", str(src), "-i", str(audio)]
        pan = 1 if i % 2 else -1  # alterna o sentido do movimento
        x = f"(iw-ow)*t/{dur:.2f}" if pan > 0 else f"(iw-ow)*(1-t/{dur:.2f})"
        fil = [f"[0:v]scale=2112:1188:force_original_aspect_ratio=increase,crop=2112:1188,setsar=1,fps={FPS},"
               f"crop={W}:{H}:x='{x}':y='(ih-oh)/2',eq=brightness=-0.10:saturation=1.08[b0]"]
    atual, n = "b0", 2
    if cd:
        png, cx, cy = cd
        entradas += ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(png)]
        fil.append(f"[{n}:v]format=rgba,fade=t=in:st=0.15:d=0.35:alpha=1[k]")
        fil.append(f"[{atual}][k]overlay=x='if(lt(t,0.5),{cx}-80+160*t,{cx})':y={cy}[b1]")
        atual, n = "b1", n + 1
    if marca and marca.exists():
        entradas += ["-i", str(marca)]
        fil.append(f"[{n}:v]scale=150:-1,format=rgba,colorchannelmixer=aa=0.8[m];[{atual}][m]overlay=W-w-40:36[b2]")
        atual, n = "b2", n + 1
    fil.append(f"[{atual}]ass='{_escapar(ass)}':fontsdir='{_escapar(FONTES)}',format=yuv420p[v]")
    saida = pasta / f"c{i:02d}.mp4"
    if com_som:  # narração por cima do som dos pedaços (whoosh + som real dos clipes)
        fil.append(f"[1:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=0:{dur:.2f}[nar];"
                   f"[0:a]aresample=48000,apad,atrim=0:{dur:.2f}[fx];[nar][fx]amix=inputs=2:duration=first:normalize=0[a]")
        mapa_audio = ["-map", "[a]"]
    else:
        mapa_audio = ["-map", "1:a", "-af", f"apad,atrim=0:{dur:.2f},aresample=48000"]
    rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", ";".join(fil),
           "-map", "[v]", *mapa_audio,
           "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-r", str(FPS),
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(saida)])
    return {"arquivo": saida, "dur": dur, "capitulo": c.get("capitulo", "")}


def montar(roteiro: dict, fontes: list[Path], cor: str, marca: Path | None, pasta: Path,
           log=print) -> tuple[Path, list[tuple[float, str]]]:
    pasta.mkdir(parents=True, exist_ok=True)
    fundos = Fundos(fontes, semente=int(roteiro.get("id", "1")) if str(roteiro.get("id", "1")).isdigit() else 7)
    voz, taxa = roteiro.get("voz", "pt-BR-AntonioNeural"), roteiro.get("taxa", "+6%")
    partes, capitulos, relogio = [], [], 0.0
    creditos, usados = [], set()
    citadas = fontes_citadas(pasta / "fontes", f"f{roteiro['id']}_")
    if citadas:
        log(f"  trechos citados disponíveis: {', '.join(sorted(citadas))}")
    for i, c in enumerate(roteiro["cenas"]):
        r = cena(i, c, voz, taxa, fundos, cor, marca, pasta, creditos, usados, citadas)
        if r["capitulo"]:
            capitulos.append((relogio, r["capitulo"]))
        relogio += r["dur"]
        partes.append(r["arquivo"])
        log(f"  cena {i + 1}/{len(roteiro['cenas'])} ok ({r['dur']:.1f}s)")
    lista = pasta / "lista.txt"
    lista.write_text("".join(f"file '{p.name}'\n" for p in partes))
    juntado = pasta / "juntado.mp4"
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy", str(juntado)])
    final = pasta / f"narrado_{roteiro['id']}.mp4"
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", str(juntado), "-c:v", "copy",
           "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(final)])
    roteiro["_creditos"] = list(dict.fromkeys(creditos))  # vão pra descrição
    return final, capitulos


def descricao(roteiro: dict, capitulos: list[tuple[float, str]], hashtags: list[str]) -> str:
    caps = "\n".join(f"{int(t // 60):02d}:{int(t % 60):02d} {nome}" for t, nome in capitulos)
    fontes = "\n".join(f"• {f}" for f in roteiro.get("fontes", []))
    resumo = roteiro["cenas"][0]["texto"]
    return (f"{roteiro['titulo']}\n{resumo}\n\n⏱️ Capítulos\n{caps}\n\n"
            + (f"📚 Fontes\n{fontes}\n\n" if fontes else "")
            + "Imagens: trailers e materiais oficiais de divulgação da Rockstar Games, usados para comentário e notícia.\n"
            + ("Fotos, matérias e trechos citados (para comentário, com crédito aos autores):\n" + "\n".join(f"• {c}" for c in roteiro.get("_creditos", [])) + "\n"
               if roteiro.get("_creditos") else "")
            + "\n"
            + " ".join(hashtags))
