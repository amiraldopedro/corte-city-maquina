#!/usr/bin/env python3
"""Robô do YouTube (roda no seu Mac, pela internet de casa).

A cada 15 minutos: olha a fila (estado/youtube.json no GitHub), e para cada vídeo pedido:
1. lê o gráfico "mais repetidos" do YouTube (ou, se não tiver, os picos de volume do áudio);
2. baixa SÓ os 3 melhores trechos (~1 minuto cada), com o login da conta reserva (nunca a do canal);
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

VERSAO = "2026-11-19a"

REPO = "amiraldopedro/corte-city-maquina"   # código + fila (público)
REPO_ARQ = REPO                               # onde sobem os vídeos: troca pro privado se a fila mandar
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
    if ssd and Path(ssd).parent.is_dir():  # /Volumes/PortableSSD existe = SSD montado
        try:
            p = Path(ssd)
            p.mkdir(exist_ok=True)
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
    for destino in (LOG, LOCAL / "robo_youtube.log"):
        try:
            with open(destino, "a") as f:
                f.write(linha + "\n")
            return
        except OSError:
            continue


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


def escolher_repo_arquivos(fila: dict):
    """A máquina avisa na fila qual é o repositório privado dos vídeos. Se esta chave não tiver acesso a ele,
    continua subindo no repositório da máquina (e avisa no log o que falta)."""
    global REPO_ARQ
    alvo = fila.get("arquivos_repo") or REPO
    if alvo == REPO_ARQ:
        return
    st, _ = api("GET", f"https://api.github.com/repos/{alvo}")
    if st == 200:
        REPO_ARQ = alvo
        log(f"  vídeos agora sobem pro repositório privado {alvo}")
    else:
        marca = LOCAL / ".aviso_arquivos"
        if not marca.exists() or time.time() - marca.stat().st_mtime > 6 * 3600:
            marca.touch()
            log(f"  a chave do robô não abre {alvo} ({st}): edite a chave no GitHub e dê acesso a esse repositório")


def release_id() -> int:
    base = f"https://api.github.com/repos/{REPO_ARQ}"
    st, d = api("GET", f"{base}/releases/tags/{TAG}")
    if st == 200:
        return d["id"]
    st, d = api("POST", f"{base}/releases", {"tag_name": TAG, "name": {"biblioteca": "Biblioteca de imagens", "fontes": "Fontes citadas nos vídeos narrados", "analise": "Análise de referências"}.get(TAG, "Trechos do YouTube (robô do Mac)"),
                                     "body": "Arquivos temporários do robô do YouTube.", "prerelease": True})
    if st not in (200, 201):
        raise RuntimeError(f"não criei a área de arquivos ({st}): {d}")
    return d["id"]


def subir(arquivo: Path, nome: str) -> int:
    rid = release_id()
    base = f"https://api.github.com/repos/{REPO_ARQ}"
    st, rel = api("GET", f"{base}/releases/{rid}")
    for a in rel.get("assets", []):
        if a["name"] == nome:
            api("DELETE", f"{base}/releases/assets/{a['id']}")
    url = f"https://uploads.github.com/repos/{REPO_ARQ}/releases/{rid}/assets?name={nome}"
    st, d = api("POST", url, arquivo.read_bytes(), tipo="video/mp4")
    if st not in (200, 201):
        raise RuntimeError(f"upload falhou ({st}): {d}")
    return d["id"]


# Conta reserva logada num perfil do Chrome (o Amiraldo escolheu): o robô usa o login dela pra
# o YouTube não tratar a internet de casa como robô. Nunca a conta do canal.
CONTA_RESERVA = ("felipe", "rezende", "resende")


def _perfil_chrome() -> str | None:
    """Pasta do perfil do Chrome onde a conta reserva está (lê o 'Local State' do Chrome)."""
    estado = Path.home() / "Library/Application Support/Google/Chrome/Local State"
    try:
        perfis = json.loads(estado.read_text()).get("profile", {}).get("info_cache", {})
    except Exception as e:
        log(f"  (não consegui ler os perfis do Chrome: {str(e)[:80]})")
        return None
    for pasta, p in perfis.items():
        nomes = " ".join(str(p.get(k, "")) for k in ("name", "gaia_name", "gaia_given_name", "user_name")).lower()
        if any(n in nomes for n in CONTA_RESERVA):
            return pasta
    log("  perfis do Chrome encontrados: " + ", ".join(f"{k}={v.get('name', '')}" for k, v in perfis.items()))
    return None


_PERFIL = _perfil_chrome()


def ytdlp(*args, capturar=False, limite=None):
    """Tenta sem login; se o YouTube pedir login (ou travar), tenta de novo com a conta reserva.
    `limite` = segundos máximos por tentativa. Sem isso: 3 min pra ler informações, 15 min pra baixar."""
    env = {**os.environ, "PATH": PATH_EXTRA + ":" + os.environ.get("PATH", "")}
    baixando = "-o" in args
    limite = limite or (900 if baixando else 180)
    # --retries/--fragment-retries baixos: quando o YouTube recusa os pedaços (403), o padrão do yt-dlp
    # (10 tentativas por pedaço) fazia um Short de 50 s ficar 1 hora travado.
    base = ["yt-dlp", "--no-warnings", "--no-playlist", "--socket-timeout", "20", "--retries", "3",
            "--fragment-retries", "3", "--abort-on-unavailable-fragments", "--cache-dir", str(PASTA / "cache")]
    tentativas = [[]]
    if _PERFIL:
        for cliente in ("web_safari,mweb", "tv,web_safari", "default"):
            tentativas.append(["--cookies-from-browser", f"chrome:{_PERFIL}", "--sleep-requests", "1",
                               "--extractor-args", f"youtube:player_client={cliente}"])
    erro = ""
    for n, extra in enumerate(tentativas):
        try:
            r = subprocess.run([*base, *extra, *args], capture_output=True, text=True, env=env, timeout=limite)
        except subprocess.TimeoutExpired:
            erro = f"travou mais de {limite // 60} min ({'sem login' if not extra else 'com a conta reserva'})"
            log(f"    yt-dlp {erro}: tentando de outro jeito")
            continue  # travar quase sempre é o YouTube segurando o vídeo: outro cliente/login costuma resolver
        if r.returncode == 0:
            return r.stdout
        erro = r.stderr.strip()[-300:] or f"yt-dlp saiu com código {r.returncode}"
        if not any(k in erro for k in ("Sign in", "cookies", "age-restricted", "not available", "reloaded", "bot",
                                       "login", "rate-limit", "403", "Forbidden", "fragment")):
            break  # erro que login não resolve (vídeo bloqueado no país, removido...)
    raise RuntimeError(erro)


def picos_heatmap(info: dict) -> list[tuple[float, float]]:
    hm = info.get("heatmap") or []
    return sorted(((h["start_time"] + h["end_time"]) / 2, h["value"]) for h in hm)


def picos_volume(link: str, pasta: Path) -> list[tuple[float, float]]:
    """Sem gráfico: baixa só o áudio (leve) e mede o volume segundo a segundo."""
    audio = pasta / "audio.m4a"
    ytdlp("-f", "worstaudio/bestaudio", "-o", str(audio), link, limite=2400)  # áudio de live de 4 h
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
        ytdlp("-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/bv*+ba/b", "--merge-output-format", "mp4",
              "-o", str(arq), link, limite=3600)
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
        ytdlp("-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/bv*+ba/b", "--merge-output-format", "mp4",
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


def tiktok_cacar(fila: dict):
    """Acha TikToks de GTA 6 estourados e põe na fila como modelo (a máquina traduz e remonta).
    Fontes: páginas de tag (quando o yt-dlp estiver com o extrator de tag funcionando — ele se
    atualiza toda noite) e os perfis da lista `contas` (funciona hoje). Roda a cada 6 h."""
    conf = fila.get("modelar_tiktok") or {}
    if not conf.get("ligado"):
        return
    marca = LOCAL / ".tiktok_cacado"
    if marca.exists() and time.time() - marca.stat().st_mtime < 6 * 3600:
        return
    marca.touch()
    hoje = datetime.now(timezone.utc).date().isoformat()
    feitos = sum(1 for m in fila.get("momentos", {}).values() if m.get("plataforma") == "tiktok"
                 and m.get("modo") == "modelo" and (m.get("pedido_em") or "")[:10] == hoje)
    vagas = int(conf.get("por_dia", 2)) - feitos
    if vagas <= 0:
        return
    fontes = ([f"https://www.tiktok.com/tag/{t}" for t in conf.get("tags", [])]
              + [f"https://www.tiktok.com/@{c.lstrip('@')}" for c in conf.get("contas", [])])
    candidatos = []
    for fonte in fontes:
        try:
            bruto = json.loads(ytdlp("--flat-playlist", "--playlist-items", "1:15", "-J", fonte))
        except Exception as e:
            log(f"  tiktok: {fonte.rsplit('/', 1)[-1]} não deu ({str(e)[:70]})")
            continue
        for e in (bruto.get("entries") or [])[:15]:
            tid = str(e.get("id") or "")
            if not tid or f"tk_{tid}" in fila.get("momentos", {}):
                continue
            url = e.get("url") or e.get("webpage_url") or ""
            views, ts = e.get("view_count"), e.get("timestamp")
            if views is None or ts is None:  # lista rasa sem números: pergunta do vídeo
                try:
                    i = json.loads(ytdlp("-J", url))
                    views, ts = i.get("view_count") or 0, i.get("timestamp") or 0
                    e["description"] = i.get("description") or e.get("title") or ""
                    e["uploader"] = i.get("uploader") or i.get("channel") or ""
                except Exception:
                    continue
            texto = f"{e.get('title') or ''} {e.get('description') or ''}"
            idade_dias = (time.time() - (ts or 0)) / 86400
            if (views or 0) < int(conf.get("min_views", 500000)) or idade_dias > int(conf.get("dias", 5)):
                continue
            if not re.search(r"gta|grand theft|vice city|leonida", texto, re.I):
                continue
            candidatos.append({"id": tid, "url": url, "views": views, "texto": texto.strip()[:120],
                               "autor": e.get("uploader") or e.get("channel") or ""})
    candidatos.sort(key=lambda c: -c["views"])
    vistos = set()
    for c in candidatos:
        if vagas <= 0:
            break
        if c["autor"] in vistos:
            continue
        vistos.add(c["autor"])
        atualizar_item(f"tk_{c['id']}", {"modo": "modelo", "status": "modelo_pendente", "plataforma": "tiktok",
                                         "link": c["url"], "titulo": c["texto"], "canal_nome": c["autor"],
                                         "views_yt": c["views"], "pedido_em": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        log(f"  🔥 tiktok na fila: {c['texto'][:60]} ({c['autor']}, {c['views']:,} views)")
        vagas -= 1


def modelo(vid: str, item: dict):
    """Short viral de referência: baixa o vídeo INTEIRO (é curto) pra máquina traduzir e remontar."""
    link = item.get("link") or f"https://www.youtube.com/watch?v={vid}"
    TEMP.mkdir(exist_ok=True)
    pasta = Path(tempfile.mkdtemp(prefix="cc_modelo_", dir=TEMP))
    try:
        info = json.loads(ytdlp("-J", link))
        arq = pasta / f"modelo_{vid}.mp4"
        ytdlp("-f", "bv*[height<=1920][ext=mp4]+ba[ext=m4a]/b[height<=1920]/bv*+ba/b",
              "--merge-output-format", "mp4", "-o", str(arq), link, limite=300)  # é um Short: 5 min sobra
        aid = subir(arq, arq.name)
        atualizar_item(vid, {"status": "modelo_baixado", "asset_id": aid,
                             "titulo": info.get("title") or item.get("titulo", ""),
                             "canal_nome": info.get("channel") or info.get("uploader") or item.get("canal_nome", ""),
                             "idioma_falado": info.get("language") or "",
                             "url_final": info.get("webpage_url") or link})
        log(f"  ✅ modelo {vid}: {(info.get('title') or '')[:60]}")
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
        ytdlp("-f", "bv*[height<=480][ext=mp4]+ba[ext=m4a]/b[height<=480]/bv*+ba/b", "--merge-output-format", "mp4",
              "-o", str(arq), link)
        try:
            ytdlp("--skip-download", "--write-auto-subs", "--write-subs", "--sub-langs", "en-orig,en", "--sleep-subtitles", "3",
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
    if item.get("modo") == "modelo":
        return modelo(vid, item)
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
            ytdlp("-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/bv*+ba/b", "--merge-output-format", "mp4",
                  "--download-sections", f"*{ini:.0f}-{fim:.0f}", "--force-keyframes-at-cuts", "-o", str(arq), link)
            aid = subir(arq, arq.name)
            segmentos.append({"asset_id": aid, "inicio": ini, "fim": fim, "duracao": fim - ini, "forca": forca})
            log(f"  trecho {i + 1}: {ini / 60:.1f}-{fim / 60:.1f} min enviado")
        longo = None
        jl = janela_longa(picos, duracao)
        if jl:
            arq = pasta / f"yt_{vid}_longo.mp4"
            ytdlp("-f", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720]/bv*+ba/b", "--merge-output-format", "mp4",
                  "--download-sections", f"*{jl[0]:.0f}-{jl[1]:.0f}", "--force-keyframes-at-cuts", "-o", str(arq), link, limite=1800)
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
    # o YouTube muda toda semana; yt-dlp velho é o motivo nº 1 de "sign in to confirm you're not a bot"
    marca = LOCAL / ".ytdlp_atualizado"
    if not marca.exists() or time.time() - marca.stat().st_mtime > 12 * 3600:
        try:
            env = {**os.environ, "PATH": PATH_EXTRA + ":" + os.environ.get("PATH", "")}
            r = subprocess.run(["yt-dlp", "-U", "--update-to", "nightly"], capture_output=True, text=True, env=env, timeout=180)
            log("  yt-dlp: " + (r.stdout.strip().splitlines() or ["ok"])[-1][:100])
            marca.touch()
        except Exception as e:
            log(f"  yt-dlp: não consegui atualizar ({str(e)[:80]})")
    log(f"  login do YouTube: perfil do Chrome '{_PERFIL}' (conta reserva)" if _PERFIL
        else "  login do YouTube: conta reserva não achada no Chrome, baixando sem login")
    _, fila = ler_fila()
    escolher_repo_arquivos(fila)
    sinal_de_vida(fila)
    try:
        tiktok_cacar(fila)
        _, fila = ler_fila()  # a caça pode ter posto itens novos
    except Exception as e:
        log(f"  tiktok: caça falhou ({str(e)[:100]})")
    pendentes = {k: v for k, v in fila.get("momentos", {}).items()
                 if v.get("status") in ("esperando", "biblioteca_pendente", "fonte_pendente", "analise_pendente", "modelo_pendente")}
    if not pendentes:
        return
    prioridade = {"fonte": 0, "modelo": 1, "analise": 2, "biblioteca": 3}  # rápidos primeiro, reacts longos por último
    # quem já falhou vai pro fim da fila: um vídeo problemático não pode segurar todos os outros
    ordem = sorted(pendentes.items(), key=lambda kv: (int(kv[1].get("tentativas", 0)),
                                                      prioridade.get(kv[1].get("modo"), 3),
                                                      kv[1].get("pedido_em") or ""))
    inicio = time.time()
    for n, (vid, item) in enumerate(ordem):
        if n and time.time() - inicio > ORCAMENTO:
            log(f"  rodada passou de {ORCAMENTO // 60} min: os outros {len(ordem) - n} ficam pra próxima (15 min)")
            break
        try:
            processar(vid, item)
        except Exception as e:
            if os.environ.get("CC_BASE") and not Path(os.environ["CC_BASE"]).is_dir():
                log("  SSD desconectou no meio do download: paro aqui e continuo quando ele voltar (não conta como erro)")
                return
            log(f"  ❌ {vid}: {e}")
            tentativas = int(item.get("tentativas", 0)) + 1
            atualizar_item(vid, {"tentativas": tentativas, "erro": str(e)[-300:],
                                 "status": "erro" if tentativas >= 3 else item.get("status", "esperando")})


ORCAMENTO = 50 * 60  # segundos por rodada; o launchd chama de novo 15 min depois


def sinal_de_vida(fila: dict):
    """Marca na fila quando o robô passou (o Studio mostra isso). No máximo 1 vez por hora."""
    marca = LOCAL / ".sinal_de_vida"
    if marca.exists() and time.time() - marca.stat().st_mtime < 3600:
        return
    try:
        for _ in range(4):
            sha, f = ler_fila()
            f["robo"] = {"visto_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "login": bool(_PERFIL), "versao": VERSAO}
            corpo = {"message": "Robô do YouTube: sinal de vida [skip ci]", "sha": sha,
                     "content": base64.b64encode(json.dumps(f, ensure_ascii=False, indent=1).encode()).decode()}
            st, _ = api("PUT", "contents/estado/youtube.json", corpo)
            if st in (200, 201):
                marca.touch()
                return
            time.sleep(3)
    except Exception as e:
        log(f"  sinal de vida não foi ({str(e)[:60]})")


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


def morar_no_mac():
    """Antes o launchd rodava o robô direto do SSD: sem SSD, nada funcionava (nem o aviso).
    Agora o robô (30 KB) mora em ~/.corte-city e só os vídeos vão pro SSD. Faz a mudança sozinho uma vez."""
    if sys.platform != "darwin":
        return
    este = Path(__file__).resolve()
    casa = LOCAL / "robo_youtube.py"
    plist = Path.home() / "Library/LaunchAgents/com.cortecity.robo-youtube.plist"
    try:
        if este != casa.resolve():
            LOCAL.mkdir(exist_ok=True)
            casa.write_bytes(este.read_bytes())
        if plist.exists() and str(casa) not in plist.read_text():
            texto = plist.read_text()
            antigo = re.search(r"<string>([^<]*robo_youtube\.py)</string>", texto)
            if antigo:
                plist.write_text(texto.replace(antigo.group(1), str(casa)))
                # recarrega o agendamento num processo separado (descarregar mata este processo)
                subprocess.Popen(["/bin/sh", "-c", f"sleep 20; launchctl unload '{plist}'; launchctl load '{plist}'"],
                                 start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                log("robô agora mora no Mac (~/.corte-city); os downloads continuam só no SSD")
    except Exception as e:
        log(f"  não consegui mudar o robô pro Mac ({str(e)[:80]})")


if __name__ == "__main__":
    TOKEN = token()
    atualizar_sozinho()
    morar_no_mac()
    main()
