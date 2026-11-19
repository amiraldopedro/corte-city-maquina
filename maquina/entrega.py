"""Entrega dos vídeos prontos: ficam como arquivos para baixar no próprio GitHub (Releases → "Vídeos prontos").

Você baixa no celular/computador e posta no YouTube pelo app ou pelo site — vídeo postado assim sai
público normalmente (vídeo enviado pela API de um projeto sem auditoria do Google fica trancado no privado).
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

TAG = "prontos"
API = "https://api.github.com"


def _repo() -> str:
    from . import arquivos
    return arquivos.repo()  # repositório privado de arquivos (ou o da máquina, se ainda não configurado)


def _cab() -> dict:
    from . import arquivos
    return arquivos.cab()


def _release() -> dict:
    r = requests.get(f"{API}/repos/{_repo()}/releases/tags/{TAG}", headers=_cab(), timeout=30)
    if r.status_code == 200:
        return r.json()
    r = requests.post(f"{API}/repos/{_repo()}/releases", headers=_cab(), timeout=30, json={
        "tag_name": TAG, "name": "Vídeos prontos para postar",
        "body": "A máquina coloca aqui cada Short e compilado pronto (vídeo + thumb). Baixe pelo painel ou por aqui e poste pelo app do YouTube.",
    })
    r.raise_for_status()
    return r.json()


def enviar_arquivo(caminho: Path, nome: str, tipo: str) -> dict:
    """Sobe um arquivo para a área de downloads. Retorna {id, url}."""
    rel = _release()
    for a in rel.get("assets", []):  # mesmo nome já existe (rodada repetida): troca
        if a["name"] == nome:
            requests.delete(f"{API}/repos/{_repo()}/releases/assets/{a['id']}", headers=_cab(), timeout=30)
    with open(caminho, "rb") as f:
        r = requests.post(f"https://uploads.github.com/repos/{_repo()}/releases/{rel['id']}/assets",
                          params={"name": nome}, data=f, timeout=600,
                          headers={**_cab(), "Content-Type": tipo})
    r.raise_for_status()
    a = r.json()
    return {"id": a["id"], "url": a["browser_download_url"]}


def apagar_arquivo(asset_id: int | None):
    if asset_id:
        requests.delete(f"{API}/repos/{_repo()}/releases/assets/{asset_id}", headers=_cab(), timeout=30)


def entregar(video: Path, capa: Path, mid: str) -> dict:
    v = enviar_arquivo(video, f"{mid}.mp4", "video/mp4")
    t = enviar_arquivo(capa, f"{mid}.jpg", "image/jpeg")
    return {"video_url": v["url"], "video_asset": v["id"], "thumb_url": t["url"], "thumb_asset": t["id"]}
