"""Vídeos e lives do YouTube que você manda pelo painel -> cortes.

Como o YouTube bloqueia download vindo do GitHub, o trabalho é dividido:
1. Painel -> `pedir`: o link entra na fila (estado/youtube.json).
2. Robozinho no seu Mac (internet de casa): acha os melhores trechos (gráfico "mais repetidos" do YouTube,
   ou os picos de volume), baixa SÓ esses trechos e sobe pro GitHub (Releases, tag youtube-brutos).
3. `processar`: cada trecho vira um momento na fila da máquina, com prioridade, e a rodada faz os Shorts.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

from .config import PASTA_ESTADO
from .estado import Estado

TAG = "youtube-brutos"


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def id_do_video(link: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})", link)
    return m.group(1) if m else None


def fila() -> Estado:
    return Estado("youtube")


REDES = {"tiktok.com": ("tk", "tiktok"), "vm.tiktok": ("tk", "tiktok"), "instagram.com": ("ig", "reels"),
         "x.com": ("x", "x"), "twitter.com": ("x", "x"), "kick.com": ("kick", "kick"),
         "facebook.com": ("fb", "facebook"), "fb.watch": ("fb", "facebook")}


def pedir(links: list[str], modo: str = "cortes") -> int:
    import hashlib
    est = fila()
    novos = 0
    for link in links:
        vid = id_do_video(link)
        rede = next((v for d, v in REDES.items() if d in link), None)
        if not vid and rede and modo == "modelo":  # TikTok/Reels/X/Kick: só no modo modelo
            vid = f"{rede[0]}_{hashlib.md5(link.encode()).hexdigest()[:10]}"
        if not vid:
            print(f"  link inválido para esse modo: {link}")
            continue
        if vid in est.momentos and est.momentos[vid].get("status") not in ("erro",):
            print(f"  já está na fila: {vid}")
            continue
        url = link if rede else f"https://www.youtube.com/watch?v={vid}"
        status = {"biblioteca": "biblioteca_pendente", "modelo": "modelo_pendente"}.get(modo, "esperando")
        est.momentos[vid] = {"id": vid, "link": url, "status": status, "modo": modo,
                             "plataforma": (rede[1] if rede else "youtube"),
                             "pedido_em": agora(), "atualizado_em": agora()}
        novos += 1
        print(f"  ✅ na fila do robô do Mac ({modo}): {url}")
    est.salvar()
    return novos


def _baixar_asset(asset_id: int, destino: Path) -> Path:
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    r = requests.get(f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}", stream=True, timeout=600,
                     headers={"Authorization": f"Bearer {token}", "Accept": "application/octet-stream"})
    r.raise_for_status()
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "wb") as f:
        for pedaco in r.iter_content(1 << 20):
            f.write(pedaco)
    return destino


def processar(cfg) -> int:
    """Trechos que o Mac já subiu viram momentos (com prioridade) na fila do canal em português."""
    est_fila = fila()
    canal = next((c for c in cfg.canais_ativos() if c.idioma == "pt"), None) or cfg.canais_ativos()[0]
    est = Estado(canal.id)
    total = 0
    for vid, item in est_fila.momentos.items():
        if item.get("status") != "baixado":
            continue
        canal_yt = item.get("canal_nome") or "YouTube"
        login = item.get("canal_handle") or item.get("canal_id") or "youtube"
        for i, seg in enumerate(item.get("segmentos", [])):
            mid = f"yt_{vid}_{i}"
            if mid in est.momentos:
                continue
            est.momentos[mid] = {
                "id": mid, "plataforma": "youtube", "streamer": login, "nome": canal_yt, "canal": canal.id,
                "video_id": None, "inicio": 0.0, "fim": float(seg.get("duracao", 60)),
                "clipe_url": None, "yt_asset": seg["asset_id"], "yt_video": vid,
                "yt_link": f"https://www.youtube.com/watch?v={vid}&t={int(seg.get('inicio', 0))}s",
                "titulos_chat": [item.get("titulo", "")], "jogo": "Grand Theft Auto VI" if re.search(
                    r"gta ?(6|vi)", item.get("titulo", ""), re.I) else "Grand Theft Auto V",
                "views": int(seg.get("forca", 1) * 1000), "n_clipes": 1, "score": 10_000 - i,
                "status": "novo", "prioridade": True, "criado_em": agora(), "atualizado_em": agora(),
                "isolar_voz": bool(item.get("isolar_voz")),
            }
            if item.get("gringo"):  # live de gringo: áudio original + legenda em português, card estilo Twitter
                est.momentos[mid].update(gringo=True, quadro="gringos", isolar_voz=False, prioridade=False,
                                         score=3_000 - i, jogo="Grand Theft Auto VI")
            total += 1
        longo = None if item.get("gringo") else item.get("longo")  # gringo em inglês não vira corte longo
        if longo and f"yt_{vid}_longo" not in est.momentos:
            mid = f"yt_{vid}_longo"
            est.momentos[mid] = {
                "id": mid, "plataforma": "youtube", "streamer": login, "nome": canal_yt, "canal": canal.id,
                "video_id": None, "inicio": 0.0, "fim": float(longo.get("duracao", 600)), "clipe_url": None,
                "yt_asset": longo["asset_id"], "yt_longo": True, "yt_video": vid,
                "yt_link": f"https://www.youtube.com/watch?v={vid}&t={int(longo.get('inicio', 0))}s",
                "titulos_chat": [item.get("titulo", "")], "jogo": "Grand Theft Auto VI" if re.search(
                    r"gta ?(6|vi)", item.get("titulo", ""), re.I) else "Grand Theft Auto V",
                "views": 0, "n_clipes": 1, "score": 20_000, "status": "novo",
                "criado_em": agora(), "atualizado_em": agora(),
            }
            total += 1
            Path("/tmp/tem_longo").write_text("1")
            print(f"  ✅ trecho grande ({longo.get('duracao', 0) / 60:.0f} min) na fila do corte longo")
        item.update(status="na_fila", atualizado_em=agora())
        print(f"  ✅ {item.get('titulo', vid)[:70]}: {len(item.get('segmentos', []))} trechos na fila de cortes")
    est.salvar()
    est_fila.salvar()
    return total


def preparar_bruto(m: dict, destino: Path) -> Path:
    if destino.exists() and destino.stat().st_size > 100_000:
        return destino
    return _baixar_asset(int(m["yt_asset"]), destino)
