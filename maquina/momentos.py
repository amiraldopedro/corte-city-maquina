"""Transforma clipes do público em "momentos".

Ideia: quando várias pessoas clipam o mesmo trecho da live, ali tem coisa boa.
Agrupamos clipes da mesma VOD cujo início está a menos de JUNTAR_SEG um do outro,
e somamos as views. Cada grupo vira um momento com uma janela de vídeo real
(um pouco antes e depois) que será baixada direto da VOD, em qualidade máxima.
"""
from __future__ import annotations

import math
import re

JUNTAR_SEG = 40     # clipes com início até 40s de distância = mesmo momento
ANTES_SEG = 10      # contexto antes do primeiro clipe (o setup da piada)
DEPOIS_SEG = 6      # sobra depois do último clipe
JANELA_MAX = 95     # janela bruta máxima baixada (a IA recorta depois)


def _score(views: int, n: int, clipadores: int | None = None) -> float:
    """Força do momento: views em escala de log (um clipe de 5 mil não vale 50x um de 100)
    × pessoas DIFERENTES que clicaram o mesmo trecho (consenso vale mais que uma pessoa clipando 3 vezes)."""
    pessoas = clipadores if clipadores else n
    return 100 * math.log10(max(views, 1) + 10) * (1 + 0.5 * (max(pessoas, 1) - 1))


def score_atual(m: dict, agora_ts: float | None = None) -> float:
    """Score que a fila usa agora: perde metade da força a cada ~12 h (momento fresco na frente)."""
    import time
    from datetime import datetime
    agora_ts = agora_ts or time.time()
    quando = m.get("clipado_em") or m.get("criado_em") or ""
    try:
        idade_h = max(0.0, (agora_ts - datetime.fromisoformat(quando.replace("Z", "+00:00")).timestamp()) / 3600)
    except ValueError:
        idade_h = 0.0
    return m.get("score", 0) * math.exp(-idade_h / 18)


def _vale(c: dict, jogos_ok: dict, jogos_palavra: dict, palavras: list[str]) -> bool:
    """Jogo liberado (GTA) entra direto; conversa/react só entra se o título do clipe falar de GTA."""
    if not jogos_ok and not jogos_palavra:
        return True  # modo teste: qualquer jogo
    if c.get("game_id") in jogos_ok:
        return True
    titulo = (c.get("title") or "").lower()
    return c.get("game_id") in jogos_palavra and any(p in titulo for p in palavras)


def agrupar(clipes: list[dict], jogos_ok: dict[str, str], streamer: str, canal: str,
            minimo_clipes: int, minimo_views: int, jogos_palavra: dict | None = None,
            palavras: list[str] | None = None, um_clipe_views: int | None = None,
            quentes: int = 6) -> list[dict]:
    com_vod: dict[str, list[dict]] = {}
    sem_vod: list[dict] = []

    for c in clipes:
        if not _vale(c, jogos_ok, jogos_palavra or {}, palavras or []):
            continue
        c["_jogo"] = (jogos_ok or {}).get(c.get("game_id")) or (jogos_palavra or {}).get(c.get("game_id")) or ""
        if c.get("video_id") and c.get("vod_offset") is not None:
            com_vod.setdefault(c["video_id"], []).append(c)
        else:
            sem_vod.append(c)

    momentos = []

    for video_id, lista in com_vod.items():
        lista.sort(key=lambda c: c["vod_offset"])
        grupo: list[dict] = []
        for c in lista:
            if grupo and c["vod_offset"] - grupo[-1]["vod_offset"] > JUNTAR_SEG:
                momentos.append(_fechar(grupo, video_id, streamer, canal))
                grupo = []
            grupo.append(c)
        if grupo:
            momentos.append(_fechar(grupo, video_id, streamer, canal))

    # VOD apagada/desligada: usa o próprio clipe (máx. 60s, qualidade do clipe)
    for c in sem_vod:
        momentos.append({
            "id": f"clip_{c['id']}",
            "streamer": streamer, "canal": canal,
            "video_id": None, "inicio": 0.0, "fim": float(c.get("duration", 30)),
            "clipe_url": c["url"], "clipe_ids": [c["id"]],
            "titulos_chat": [c.get("title", "")],
            "views": c.get("view_count", 0), "n_clipes": 1, "clipadores": 1,
            **({"clipado_em": c["created_at"]} if c.get("created_at") else {}),
            "score": _score(c.get("view_count", 0), 1) * 0.7,  # penaliza: sem contexto
        })

    # Momento "quente": muita gente clipando o mesmo trecho da live = algo forte aconteceu, mesmo com poucas
    # views (na live acontecendo agora os clipes acabaram de nascer e ainda não têm views).
    return [m for m in momentos
            if (m.get("clipadores", 1) >= quentes)
            or ((m["n_clipes"] >= minimo_clipes or m["views"] >= (um_clipe_views or minimo_views * 3))
                and m["views"] >= minimo_views)]


def _fechar(grupo: list[dict], video_id: str, streamer: str, canal: str) -> dict:
    inicio = max(0.0, min(c["vod_offset"] for c in grupo) - ANTES_SEG)
    fim = max(c["vod_offset"] + float(c.get("duration", 30)) for c in grupo) + DEPOIS_SEG
    if fim - inicio > JANELA_MAX:
        # centraliza no clipe mais visto
        top = max(grupo, key=lambda c: c.get("view_count", 0))
        centro = top["vod_offset"] + float(top.get("duration", 30)) / 2
        inicio = max(0.0, centro - JANELA_MAX / 2)
        fim = inicio + JANELA_MAX
    views = sum(c.get("view_count", 0) for c in grupo)
    titulos = sorted(grupo, key=lambda c: -c.get("view_count", 0))
    clipadores = len({c.get("creator_name") or c.get("creator_id") or c["id"] for c in grupo})
    clipado_em = max((c.get("created_at") or "" for c in grupo), default="")
    return {
        "id": f"{video_id}_{int(inicio)}",
        "streamer": streamer, "canal": canal,
        "video_id": video_id, "inicio": float(inicio), "fim": float(fim),
        "clipe_url": titulos[0]["url"],
        "clipe_ids": [c["id"] for c in grupo],
        "titulos_chat": [c.get("title", "") for c in titulos[:8]],
        "views": views, "n_clipes": len(grupo), "clipadores": clipadores,
        **({"clipado_em": clipado_em} if clipado_em else {}),
        "score": _score(views, len(grupo), clipadores),
        "jogo": titulos[0].get("_jogo", ""),
    }


GTA6_PALAVRAS = ("gta 6", "gta vi", "gta6", "gtavi", "trailer", "lucia", "jason", "vice city", "leonida",
                 "rockstar", "lançamento", "pre load", "pré-carregamento", "adiamento", "adiad")


def fala_de_gta6(m: dict) -> bool:
    jogo = (m.get("jogo") or "").lower()
    if jogo.endswith(" vi"):
        return True
    texto = " ".join(m.get("titulos_chat", [])).lower()
    return bool(m.get("evento")) or any(p in texto for p in GTA6_PALAVRAS)


def quadro(m: dict) -> str:
    """Organiza o amontoado: gta6 (tudo sobre o GTA 6), rp (GTA RP / GTA V), classicos (outros GTAs)."""
    jogo = (m.get("jogo") or "").lower()
    if fala_de_gta6(m):
        return "gta6"
    if "grand theft auto v" == jogo or "rp" in jogo or not jogo or jogo in ("just chatting", "irl"):
        return "rp"
    return "classicos"


# o que mais roda na semana do lançamento (primeiras reações, bugs, comparações, segredos, dinheiro)
TEMAS_LANCAMENTO = re.compile(r"bug|glitch|f[ií]sica|pol[ií]cia|carro|primeir|rea[çc][ãa]o|reagindo|segredo|easter|"
                              r"escondid|gta ?5|gta ?v\b|compar|dinheiro|mapa|npc|tubar|jacar|crocodil", re.I)


def priorizar(m: dict) -> dict:
    """GTA 6 sempre na frente da fila (o canal é sobre o GTA 6)."""
    if not m.get("_priorizado"):
        m["quadro"] = quadro(m)
        # react antigo de trailer conta menos que clipe fresco do GTA 6
        # peso extra só quando o JOGO é GTA 6 de verdade ("Jason"/"Lucia" no título também aparecem no RP)
        jogo_gta6 = (m.get("jogo") or "").lower().endswith(" vi")
        peso = 1.0 if m.get("evento") else 2.0 if jogo_gta6 else 1.2 if m["quadro"] == "gta6" else 1.0
        if jogo_gta6 and TEMAS_LANCAMENTO.search(" ".join(m.get("titulos_chat", []))):
            peso *= 1.3  # tema que o público procura no lançamento
        m["score"] = m.get("score", 0) * peso
        m["_priorizado"] = True
        m["score_v"] = 2
    return m


def reescalar(m: dict) -> dict:
    """Momentos da fila antiga (score por views brutas) passam pra escala nova."""
    if m.get("score_v") != 2 and m.get("status") == "novo" and not m.get("yt_asset"):
        m["score"] = _score(m.get("views", 0), m.get("n_clipes", 1), m.get("clipadores"))
        m["_priorizado"] = False
        priorizar(m)
        m["score_v"] = 2
    return m
