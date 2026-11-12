"""Clipes da Kick por um serviço de dados pago (anysite.io).

A API oficial da Kick não tem rota de clipes, e o site bloqueia robôs. Então a gente
não raspa a Kick: o serviço entrega a lista de clipes e o vídeo vem do link público
do clipe (clips.kick.com). Sem a chave KICK_API_KEY nos Secrets, essa parte fica desligada.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import requests

API = "https://api.anysite.io/api/kick/channels/clips"
JUNTAR_SEG = 40


def ligado() -> bool:
    return bool(os.getenv("KICK_API_KEY"))


def _data(txt: str | None):
    if not txt:
        return None
    try:
        return datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except ValueError:
        return None


def _lista(dados) -> list[dict]:
    """O serviço pode devolver a lista direto ou dentro de uma chave."""
    if isinstance(dados, list):
        return dados
    for chave in ("clips", "data", "results", "items", "result"):
        v = dados.get(chave) if isinstance(dados, dict) else None
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            dentro = _lista(v)
            if dentro:
                return dentro
    return []


def normalizar(c: dict, slug: str) -> dict:
    cat = c.get("category") or {}
    vod = c.get("vod") or {}
    return {
        "id": "kick_" + str(c.get("id") or c.get("clip_id")),
        "title": c.get("title") or "",
        "view_count": int(c.get("view_count") or c.get("views") or 0),
        "duration": float(c.get("duration") or 30),
        "url": c.get("video_url") or c.get("clip_url") or c.get("playback_url")
               or f"https://kick.com/{slug}/clips/{c.get('id')}",
        "jogo": (cat.get("name") if isinstance(cat, dict) else str(cat)) or "",
        "vod": (vod.get("id") if isinstance(vod, dict) else vod) or c.get("livestream_id") or "",
        "inicio": _data(c.get("started_at") or c.get("created_at")),
        "criado": _data(c.get("created_at")),
    }


def clipes(slug: str, horas: int, quantos: int = 40) -> list[dict]:
    chave = os.getenv("KICK_API_KEY", "")
    for tentativa in range(3):
        r = requests.post(API, json={"slug": slug, "count": quantos},
                          headers={"access-token": chave, "Content-Type": "application/json"}, timeout=120)
        if r.status_code == 412:
            raise LookupError("canal não existe na Kick")
        if r.status_code in (429, 500, 502, 503) and tentativa < 2:
            time.sleep(10 * (tentativa + 1))
            continue
        r.raise_for_status()
        break
    limite = datetime.now(timezone.utc) - timedelta(hours=horas)
    saida = []
    for c in _lista(r.json()):
        n = normalizar(c, slug)
        if n["url"] and (n["criado"] is None or n["criado"] >= limite):
            saida.append(n)
    return saida


def vale(c: dict, jogos: list[str], palavras: list[str]) -> bool:
    """GTA/RDR pela categoria; conversa/react só se o título falar do jogo."""
    jogo = c["jogo"].lower()
    if any(j.lower() in jogo or jogo in j.lower() for j in jogos if jogo):
        return True
    titulo = c["title"].lower()
    return any(p in titulo for p in palavras)


def momentos(lista: list[dict], streamer: str, canal: str, minimo_views: int) -> list[dict]:
    """Clipes da mesma live com início a menos de 40s = mesmo momento (fica o mais visto)."""
    lista = sorted(lista, key=lambda c: (str(c["vod"]), c["inicio"] or datetime.min.replace(tzinfo=timezone.utc)))
    grupos: list[list[dict]] = []
    for c in lista:
        g = grupos[-1] if grupos else None
        if (g and c["vod"] and c["vod"] == g[-1]["vod"] and c["inicio"] and g[-1]["inicio"]
                and (c["inicio"] - g[-1]["inicio"]).total_seconds() <= JUNTAR_SEG):
            g.append(c)
        else:
            grupos.append([c])
    saida = []
    for g in grupos:
        g.sort(key=lambda c: -c["view_count"])
        top, views = g[0], sum(c["view_count"] for c in g)
        if views < minimo_views:
            continue
        saida.append({
            "id": f"clip_{top['id']}", "plataforma": "kick",
            "streamer": streamer, "canal": canal,
            "video_id": None, "inicio": 0.0, "fim": top["duration"],
            "clipe_url": top["url"], "clipe_ids": [c["id"] for c in g],
            "titulos_chat": [c["title"] for c in g[:8]],
            "views": views, "n_clipes": len(g),
            "score": (views * (1 + 0.6 * (len(g) - 1))) * 0.7,
            "jogo": top["jogo"],
        })
    return saida
