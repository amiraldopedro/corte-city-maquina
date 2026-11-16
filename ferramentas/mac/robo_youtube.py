#!/usr/bin/env python3
"""Robô do YouTube (roda no seu Mac, pela internet de casa).

A cada 15 minutos: olha a fila (estado/youtube.json no GitHub), e para cada vídeo pedido:
1. lê o gráfico "mais repetidos" do YouTube (ou, se não tiver, os picos de volume do áudio);
2. baixa SÓ os 3 melhores trechos (~1 minuto cada), sem login e sem cookies da sua conta;
3. sobe os trechos pro GitHub e avisa a máquina, que faz os Shorts.

Só usa o que já vem no Mac (Python 3) + yt-dlp e ffmpeg (baixados prontos pelo instalador em ~/.corte-city/bin).
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = "amiraldopedro/corte-city-maquina"
TAG = "youtube-brutos"
TRECHOS = 3
JANELA = 70          # segundos por trecho curto (vira Short)
JANELA_LONGA = 600   # trecho grande (vira corte longo / react completo): 10 min em volta da parte mais vista
LONGO_A_PARTIR = 8 * 60   # vídeo com mais de 8 min também ganha o trecho grande
# Arquivos temporários e registro ficam no SSD (CC_BASE). Se o SSD estiver desconectado ou o macOS
# não deixar escrever nele, usa a pasta do próprio robô no Mac, pra nunca parar.
LOCAL = Path.home() / ".corte-city"  # nunca o SSD (senão o teste de SSD conectado se engana)


def _base() -> Path:
    ssd = os.environ.get("CC_BASE")
    if ssd:
        try:
            p = Path(ssd)
            p.mkdir(parents=True, exist_ok=True)
            (p / ".teste").write_text("ok")
            return p
        except OSError:
            pass
    return LOCAL


PASTA = _base()
LOG = PASTA / "robo_youtube.log"
TEMP = PASTA / "temporarios"
PATH_EXTRA = f"{Path.home()}/.corte-city/bin:/opt/homebrew/bin:/usr/local/bin"


def log(msg: str):
    linha = f"[{datetime.now():%d/%m %H:%M:%S}] {msg}"
    print(linha, flush=True)
    with open(LOG, "a") as f:
        f.write(linha + "\n")


def token() -> str:
    r = subprocess.run(["security", "find-generic-password", "-s", "corte-city-github", "-w"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit("Chave do GitHub não encontrada. Rode o instalador de novo.")
    return r.stdout.strip()


def api(metodo: str, url: str, dados=None, tipo="application/json", bruto=False):
    if not url.startswith("http"):
        url = f"https://api.github.com/repos/{REPO}/{url}"
    corpo = dados if isinstance(dados, (bytes, type(None))) else json.dumps(dados).encode()
    req = urllib.request.Request(url, data=corpo, method=metodo, headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
        "Content-Type": tipo, "User-Agent": "corte-city-robo"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            texto = r.read()
            return (r.status, texto if bruto else (json.loads(texto) if texto else {}))
    except urllib.error.HTTPError as e:
        return (e.code, {"erro": e.read().decode(errors="ignore")[:300]})


def ler_fila():
    st, d = api("GET", "contents/estado/youtube.json?ref=main")
    if st == 404:
        return None, {"momentos": {}}
    if st != 200:
        raise RuntimeError(f"não li a fila ({st}): {d}")
    return d["sha"], json.loads(base64.b64decode(d["content"]))


def atualizar_item(vid: str, mudancas: dict):
    """Lê a versão mais nova da fila, muda só este vídeo e salva (tenta de novo se alguém salvou junto)."""
    for _ in range(6):
        sha, fila = ler_fila()
        item = fila.setdefault("momentos", {}).setdefault(vid, {"id": vid})
        item.update(mudancas, atualizado_em=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        corpo = {"message": f"Robô do YouTube: {vid} {mudancas.get('status', '')} [skip ci]",
                 "content": base64.b64encode(json.dumps(fila, ensure_ascii=False, indent=1).encode()).decode()}
        if sha:
            corpo["sha"] = sha
        st, d = api("PUT", "contents/estado/youtube.json", corpo)
        if st in (200, 201):
            return
        time.sleep(4)
    raise RuntimeError("não consegui salvar a fila")


def release_id() -> int:
    st, d = api("GET", f"releases/tags/{TAG}")
    if st == 200:
        return d["id"]
    st, d = api("POST", "releases", {"tag_name": TAG, "name": {"biblioteca": "Biblioteca de imagens", "fontes": "Fontes citadas nos vídeos narrados", "analise": "Análise de referências"}.get(TAG, "Trechos do YouTube (robô do Mac)"),
                                     "body": "Arquivos temporários do robô do YouTube.", "prerelease": True})
    if st not in (200, 201):
        raise RuntimeError(f"não criei a área de arquivos ({st}): {d}")
    return d["id"]


def subir(arquivo: Path, nome: str) -> int:
    rid = release_id()
    st, rel = api("GET", f"releases/{rid}")
    for a in rel.get("assets", []):
        if a["name"] == nome:
            api("DELETE", f"releases/assets/{a['id']}")
    url = f"https://uploads.github.com/repos/{REPO}/releases/{rid}/assets?name={nome}"
    st, d = api("POST", url, arquivo.read_bytes(), tipo="video/mp4")
    if st not in (200, 201):
        raise RuntimeError(f"upload falhou ({st}): {d}")
    return d["id"]


def ytdlp(*args, capturar=False):
    env = {**os.environ, "PATH": PATH_EXTRA + ":" + os.environ.get("PATH", "")}
    r = subprocess.run(["yt-dlp", "--no-warnings", "--no-playlist", "--cache-dir", str(PASTA / "cache"), *args],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-300:])
    return r.stdout


def picos_heatmap(info: dict) -> list[tuple[float, float]]:
    hm = info.get("heatmap") or []
    return sorted(((h["start_time"] + h["end_time"]) / 2, h["value"]) for h in hm)


def picos_volume(link: str, pasta: Path) -> list[tuple[float, float]]:
    """Sem gráfico: baixa só o áudio (leve) e mede o volume segundo a segundo."""
    audio = pasta / "audio.m4a"
    ytdlp("-f", "worstaudio/bestaudio", "-o", str(audio), link)
    env = {**os.environ, "PATH": PATH_EXTRA + ":" + os.environ.get("PATH", "")}
    r = subprocess.run(["ffmpeg", "-i", str(audio), "-af",
                        "aresample=8000,asetnsamples=n=8000,astats=metadata=1:reset=1,"
                        "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"],
                       capture_output=True, text=True, env=env)
    valores = [float(v) if v not in ("-inf", "inf") else -90.0
               for v in re.findall(r"RMS_level=(-?[\d.]+|-?inf)", r.stdout)]
    suave = []
    for i in range(len(valores)):
        janela = valores[max(0, i - 5): i + 5]
        suave.append((float(i), sum(janela) / len(janela)))
    return suave


def escolher(picos: list[tuple[float, float]], duracao: float) -> list[tuple[float, float, float]]:
    if duracao <= JANELA * 1.5:
        return [(0.0, duracao, 1.0)]
    escolhidos = []
    for t, forca in sorted(picos, key=lambda p: -p[1]):
        if t < 20 or t > duracao - 10:   # ignora abertura e fim
            continue
        if all(abs(t - e[0]) > JANELA * 1.4 for e in escolhidos):
            escolhidos.append((t, forca))
        if len(escolhidos) == TRECHOS:
            break
    maior = max((f for _, f in escolhidos), default=1) or 1
    saida = []
    for t, forca in sorted(escolhidos):
        ini = max(0.0, t - JANELA * 0.6)
        saida.append((ini, min(duracao, ini + JANELA), round(abs(forca / maior), 3)))
    return saida


def janela_longa(picos: list[tuple[float, float]], duracao: float) -> tuple[float, float] | None:
    """Os 10 minutos seguidos com mais "repetições" (ou mais volume) do vídeo."""
    if duracao < LONGO_A_PARTIR:
        return None
    if duracao <= JANELA_LONGA * 1.2:
        return (0.0, duracao)
    if not picos:
        return (max(0.0, duracao / 2 - JANELA_LONGA / 2), min(duracao, duracao / 2 + JANELA_LONGA / 2))
    minimo = min(f for _, f in picos)
    melhor, melhor_soma = 0.0, -1.0
    inicio = 0.0
    while inicio + JANELA_LONGA <= duracao:
        soma = sum(f - minimo for t, f in picos if inicio <= t < inicio + JANELA_LONGA)
        if soma > melhor_soma:
            melhor, melhor_soma = inicio, soma
        inicio += 30
    return (melhor, melhor + JANELA_LONGA)


def biblioteca(vid: str, item: dict):
    """Vídeo inteiro (ex.: trailer oficial) pra servir de imagem de fundo nos vídeos narrados."""
    link = item.get("link") or f"https://www.youtube.com/watch?v={vid}"
    TEMP.mkdir(exist_ok=True)
    pasta = Path(tempfile.mkdtemp(prefix="cc_bib_", dir=TEMP))
    try:
        info = json.loads(ytdlp("-J", link))
        if float(info.get("duration") or 0) > 30 * 60:
            raise RuntimeError("vídeo longo demais pra biblioteca (máximo 30 min)")
        arq = pasta / f"bib_{vid}.mp4"
        ytdlp("-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/b", "--merge-output-format", "mp4",
              "-o", str(arq), link)
        global TAG
        antigo, TAG = TAG, "biblioteca"
        try:
            aid = subir(arq, arq.name)
        finally:
            TAG = antigo
        atualizar_item(vid, {"status": "biblioteca_ok", "titulo": info.get("title", ""), "asset_id": aid,
                             "duracao": info.get("duration")})
        log(f"  ✅ biblioteca: {info.get('title', '')[:60]}")
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def fonte(vid: str, item: dict):
    """Trecho curto (3 a 10 s) de um vídeo de terceiros (YouTube ou X) pra citar num vídeo narrado."""
    link = item["link"]
    TEMP.mkdir(exist_ok=True)
    pasta = Path(tempfile.mkdtemp(prefix="cc_fonte_", dir=TEMP))
    try:
        info = json.loads(ytdlp("-J", link))
        if info.get("_type") == "playlist":  # busca ytsearch1: pega o primeiro resultado
            info = (info.get("entries") or [{}])[0]
            link = info.get("webpage_url") or link
        ini, fim = float(item.get("ini", 0)), float(item.get("fim", 8))
        arq = pasta / f"{vid}.mp4"
        ytdlp("-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/b", "--merge-output-format", "mp4",
              "--download-sections", f"*{ini:.1f}-{fim:.1f}", "--force-keyframes-at-cuts", "-o", str(arq), link)
        global TAG
        antigo, TAG = TAG, "fontes"
        try:
            aid = subir(arq, arq.name)
        finally:
            TAG = antigo
        atualizar_item(vid, {"status": "fonte_ok", "asset_id": aid, "titulo": info.get("title", ""),
                             "canal_nome": info.get("channel") or info.get("uploader") or "",
                             "url_final": info.get("webpage_url") or link})
        log(f"  ✅ fonte {vid}: {info.get('title', '')[:60]}")
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def analise(vid: str, item: dict):
    """Estuda um vídeo de referência: legenda, cortes por minuto e folhas de quadros (a cada 2 s)."""
    import zipfile
    link = item["link"]
    TEMP.mkdir(exist_ok=True)
    pasta = Path(tempfile.mkdtemp(prefix="cc_analise_", dir=TEMP))
    try:
        info = json.loads(ytdlp("-J", link))
        rid = info["id"]
        arq = pasta / "v.mp4"
        ytdlp("-f", "bv*[height<=480][ext=mp4]+ba[ext=m4a]/b[height<=480]/b", "--merge-output-format", "mp4",
              "-o", str(arq), link)
        try:
            ytdlp("--skip-download", "--write-auto-subs", "--write-subs", "--sub-langs", "en.*,en,pt.*",
                  "--sub-format", "json3", "-o", str(pasta / "leg"), link)
        except Exception as e:
            log(f"  (sem legenda: {str(e)[:80]})")
        env = {**os.environ, "PATH": PATH_EXTRA + ":" + os.environ.get("PATH", "")}
        (pasta / "folhas").mkdir()
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(arq), "-vf",
                        "fps=1/2,scale=320:-2,drawtext=text='%{pts\\:hms}':fontcolor=yellow:fontsize=18:x=4:y=4,tile=6x8",
                        str(pasta / "folhas" / "f%03d.jpg")], env=env, check=False)
        if not list((pasta / "folhas").glob("*.jpg")):  # ffmpeg sem fonte pro drawtext
            subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(arq), "-vf", "fps=1/2,scale=320:-2,tile=6x8",
                            str(pasta / "folhas" / "f%03d.jpg")], env=env, check=False)
        cortes = subprocess.run(["ffmpeg", "-i", str(arq), "-vf", "select='gt(scene,0.32)',showinfo", "-f", "null", "-"],
                                capture_output=True, text=True, env=env).stderr
        tempos = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", cortes)]
        resumo = {k: info.get(k) for k in ("id", "title", "channel", "channel_follower_count", "view_count", "like_count",
                                           "comment_count", "duration", "upload_date", "description", "chapters", "tags",
                                           "heatmap")}
        resumo["cortes"] = tempos
        destino = pasta / f"analise_{rid}.zip"
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("info.json", json.dumps(resumo, ensure_ascii=False, indent=1))
            for f in list(pasta.glob("leg*")) + sorted((pasta / "folhas").glob("*.jpg")):
                z.write(f, f.name if f.parent == pasta else f"folhas/{f.name}")
            try:
                t = urllib.request.urlopen(info.get("thumbnail"), timeout=30).read()
                z.writestr("thumb.jpg", t)
            except Exception:
                pass
        global TAG
        antigo, TAG = TAG, "analise"
        try:
            aid = subir(destino, destino.name)
        finally:
            TAG = antigo
        atualizar_item(vid, {"status": "analise_ok", "asset_id": aid, "titulo": info.get("title", "")})
        log(f"  ✅ análise {rid}: {info.get('title', '')[:60]} ({len(tempos)} cortes)")
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def processar(vid: str, item: dict):
    if item.get("modo") == "analise":
        return analise(vid, item)
    if item.get("modo") == "biblioteca":
        return biblioteca(vid, item)
    if item.get("modo") == "fonte":
        return fonte(vid, item)
    link = item.get("link") or f"https://www.youtube.com/watch?v={vid}"
    log(f"vídeo {vid}: lendo informações")
    info = json.loads(ytdlp("-J", link))
    if info.get("is_live"):
        log(f"  {vid} ainda está ao vivo: tento de novo quando a live acabar")
        return
    duracao = float(info.get("duration") or 0)
    TEMP.mkdir(exist_ok=True)
    pasta = Path(tempfile.mkdtemp(prefix="cc_yt_", dir=TEMP))
    try:
        picos = picos_heatmap(info)
        origem = "mais repetidos"
        if not picos:
            picos, origem = picos_volume(link, pasta), "picos de volume"
        trechos = escolher(picos, duracao)
        log(f"  {info.get('title', '')[:60]} ({duracao / 60:.0f} min): {len(trechos)} trechos por {origem}")
        segmentos = []
        for i, (ini, fim, forca) in enumerate(trechos):
            arq = pasta / f"yt_{vid}_{i}.mp4"
            ytdlp("-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/b", "--merge-output-format", "mp4",
                  "--download-sections", f"*{ini:.0f}-{fim:.0f}", "--force-keyframes-at-cuts", "-o", str(arq), link)
            aid = subir(arq, arq.name)
            segmentos.append({"asset_id": aid, "inicio": ini, "fim": fim, "duracao": fim - ini, "forca": forca})
            log(f"  trecho {i + 1}: {ini / 60:.1f}-{fim / 60:.1f} min enviado")
        longo = None
        jl = janela_longa(picos, duracao)
        if jl:
            arq = pasta / f"yt_{vid}_longo.mp4"
            ytdlp("-f", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720]/b", "--merge-output-format", "mp4",
                  "--download-sections", f"*{jl[0]:.0f}-{jl[1]:.0f}", "--force-keyframes-at-cuts", "-o", str(arq), link)
            longo = {"asset_id": subir(arq, arq.name), "inicio": jl[0], "fim": jl[1], "duracao": jl[1] - jl[0]}
            log(f"  trecho grande: {jl[0] / 60:.1f}-{jl[1] / 60:.1f} min enviado (vira corte longo)")
        atualizar_item(vid, {"status": "baixado", "longo": longo, "titulo": info.get("title", ""),
                             "canal_nome": info.get("channel") or info.get("uploader") or "",
                             "canal_handle": (info.get("uploader_id") or "").lstrip("@") or info.get("channel_id", ""),
                             "canal_id": info.get("channel_id", ""), "duracao": duracao, "segmentos": segmentos})
        st, _ = api("POST", "actions/workflows/youtube.yml/dispatches",
                    {"ref": "main", "inputs": {"acao": "processar"}})
        log(f"  ✅ {vid} pronto, máquina avisada ({st})")
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def main():
    if PASTA == LOCAL and os.environ.get("CC_BASE"):
        log(f"SanDisk desconectado ({os.environ['CC_BASE']}): esperando ele voltar, nada é baixado no Mac")
        return
    if not shutil.which("yt-dlp", path=PATH_EXTRA + ":" + os.environ.get("PATH", "")):
        log("yt-dlp não encontrado. Rode o instalador de novo.")
        return
    _, fila = ler_fila()
    pendentes = {k: v for k, v in fila.get("momentos", {}).items()
                 if v.get("status") in ("esperando", "biblioteca_pendente", "fonte_pendente", "analise_pendente")}
    if not pendentes:
        return
    for vid, item in pendentes.items():
        try:
            processar(vid, item)
        except Exception as e:
            log(f"  ❌ {vid}: {e}")
            tentativas = int(item.get("tentativas", 0)) + 1
            atualizar_item(vid, {"tentativas": tentativas, "erro": str(e)[:300],
                                 "status": "erro" if tentativas >= 3 else item.get("status", "esperando")})


def atualizar_sozinho():
    """Se a versão do robô no GitHub mudou, troca este arquivo e roda a nova versão."""
    try:
        st, d = api("GET", "contents/ferramentas/mac/robo_youtube.py?ref=main")
        if st != 200:
            return
        novo = base64.b64decode(d["content"])
        este = Path(__file__).resolve()
        if novo.strip() and novo != este.read_bytes():
            este.write_bytes(novo)
            log("robô atualizado pelo GitHub")
            os.execv(sys.executable, [sys.executable, str(este)])
    except Exception as e:
        log(f"não consegui checar atualização ({str(e)[:80]})")


if __name__ == "__main__":
    TOKEN = token()
    atualizar_sozinho()
    main()
