#!/usr/bin/env python3
"""Robô do YouTube (roda no seu Mac, pela internet de casa).

A cada 15 minutos: olha a fila (estado/youtube.json no GitHub), e para cada vídeo pedido:
1. lê o gráfico "mais repetidos" do YouTube (ou, se não tiver, os picos de volume do áudio);
2. baixa SÓ os 3 melhores trechos (~1 minuto cada), sem login e sem cookies da sua conta;
3. sobe os trechos pro GitHub e avisa a máquina, que faz os Shorts.

Só usa o que já vem no Mac (Python 3) + yt-dlp e ffmpeg (instalados pelo Homebrew).
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
JANELA = 70          # segundos por trecho
PASTA = Path.home() / ".corte-city"
LOG = PASTA / "robo_youtube.log"
PATH_EXTRA = "/opt/homebrew/bin:/usr/local/bin"


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
    st, d = api("POST", "releases", {"tag_name": TAG, "name": "Trechos do YouTube (robô do Mac)",
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
    r = subprocess.run(["yt-dlp", "--no-warnings", "--no-playlist", *args], capture_output=True, text=True, env=env)
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


def processar(vid: str, item: dict):
    link = item.get("link") or f"https://www.youtube.com/watch?v={vid}"
    log(f"vídeo {vid}: lendo informações")
    info = json.loads(ytdlp("-J", link))
    if info.get("is_live"):
        log(f"  {vid} ainda está ao vivo: tento de novo quando a live acabar")
        return
    duracao = float(info.get("duration") or 0)
    pasta = Path(tempfile.mkdtemp(prefix="cc_yt_"))
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
        atualizar_item(vid, {"status": "baixado", "titulo": info.get("title", ""),
                             "canal_nome": info.get("channel") or info.get("uploader") or "",
                             "canal_handle": (info.get("uploader_id") or "").lstrip("@") or info.get("channel_id", ""),
                             "canal_id": info.get("channel_id", ""), "duracao": duracao, "segmentos": segmentos})
        st, _ = api("POST", "actions/workflows/youtube.yml/dispatches",
                    {"ref": "main", "inputs": {"acao": "processar"}})
        log(f"  ✅ {vid} pronto, máquina avisada ({st})")
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def main():
    PASTA.mkdir(exist_ok=True)
    if not shutil.which("yt-dlp", path=PATH_EXTRA + ":" + os.environ.get("PATH", "")):
        log("yt-dlp não encontrado. Rode o instalador de novo.")
        return
    _, fila = ler_fila()
    pendentes = {k: v for k, v in fila.get("momentos", {}).items() if v.get("status") == "esperando"}
    if not pendentes:
        return
    for vid, item in pendentes.items():
        try:
            processar(vid, item)
        except Exception as e:
            log(f"  ❌ {vid}: {e}")
            tentativas = int(item.get("tentativas", 0)) + 1
            atualizar_item(vid, {"tentativas": tentativas, "erro": str(e)[:300],
                                 "status": "erro" if tentativas >= 3 else "esperando"})


if __name__ == "__main__":
    TOKEN = token()
    main()
