"""Envio pro YouTube num lugar só: nunca posta o mesmo vídeo duas vezes e respeita a cota diária.

- Cada envio custa ~1.700 unidades da cota (vídeo 1.600 + thumb 50 + playlist 50). A cota padrão é 10.000
  por dia (o dia do YouTube vira à meia-noite do Pacífico). A máquina conta o que gastou em estado/<canal>.json.
- Sem cota: o vídeo fica "aguardando_cota" com o arquivo guardado nos downloads (GitHub Releases) e sobe
  na próxima rodada que tiver cota, sem precisar montar de novo.
- Assim que o YouTube devolve o ID, ele é gravado e a memória é salva no repositório na hora.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .estado import agora

CUSTO_ENVIO = 1700
COTA_DIA = int(os.getenv("YT_COTA_DIA", "10000"))


def _dia() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def cota_usada(est) -> int:
    return int((est.dados.get("cota") or {}).get(_dia(), 0))


def tem_cota(est, envios: int = 1) -> bool:
    return cota_usada(est) + CUSTO_ENVIO * envios <= COTA_DIA


def _gastar(est, unidades: int = CUSTO_ENVIO):
    c = est.dados.setdefault("cota", {})
    c[_dia()] = c.get(_dia(), 0) + unidades
    for d in sorted(c)[:-10]:  # guarda só os últimos dias
        c.pop(d, None)


def _cota_estourou(e: Exception) -> bool:
    t = str(e)
    return "quotaExceeded" in t or "uploadLimitExceeded" in t or "dailyLimitExceeded" in t


def publicar(est, mid: str, yt, video: Path, yt_titulo: str, yt_descricao: str, yt_tags: list[str], idioma: str,
             publicar_em: str | None, capa: Path | None, playlist: str = "", log=print, **extras) -> str | None:
    """Sobe o vídeo do momento `mid`. Devolve o ID do YouTube, ou None se ficou esperando cota.
    `extras` são gravados no momento junto com o resultado."""
    m = est.momentos[mid]
    if m.get("youtube_id"):  # já subiu antes (rodada que caiu no meio): nunca reenviar
        log(f"    já estava no YouTube: https://youtu.be/{m['youtube_id']}")
        return m["youtube_id"]
    pendente = {"titulo": yt_titulo, "descricao": yt_descricao, "tags": yt_tags, "idioma": idioma, "playlist": playlist,
                "publicar_em": publicar_em, "horario_fixo": bool(extras.pop("horario_fixo", False))}
    if not tem_cota(est):
        est.atualizar(mid, status="aguardando_cota", envio_pendente=pendente, **extras)
        est.salvar()
        log(f"    ⏸️  cota do YouTube de hoje acabou ({cota_usada(est)}/{COTA_DIA}): sobe na próxima rodada")
        return None
    try:
        vid = yt.enviar(video, yt_titulo, yt_descricao, yt_tags, idioma, publicar_em, capa)
    except Exception as e:
        if _cota_estourou(e):
            est.dados.setdefault("cota", {})[_dia()] = COTA_DIA
            est.atualizar(mid, status="aguardando_cota", envio_pendente=pendente, **extras)
            est.salvar()
            log("    ⏸️  o YouTube disse que a cota acabou: sobe na próxima rodada")
            return None
        raise
    _gastar(est)
    est.atualizar(mid, status="postado", youtube_id=vid, publicar_em=publicar_em, postado_em=agora(),
                  envio_pendente=None, **extras)
    est.salvar()
    from .sincronizar import salvar_agora
    salvar_agora(f"postado {mid}")
    if playlist:
        try:
            yt.por_na_playlist(vid, playlist)
        except Exception as e:
            log(f"    aviso: não entrou na playlist ({str(e)[:100]})")
    return vid


def _baixar_asset(url: str, destino: Path) -> Path:
    """Baixa um arquivo dos downloads (GitHub Releases, repositório privado)."""
    import requests
    from . import entrega
    asset = url.rsplit("/", 1)[-1]
    rel = requests.get(f"{entrega.API}/repos/{entrega._repo()}/releases/tags/{entrega.TAG}",
                       headers=entrega._cab(), timeout=30).json()
    a = next((x for x in rel.get("assets", []) if x["name"] == asset), None)
    if not a:
        raise FileNotFoundError(f"{asset} não está mais nos downloads")
    with requests.get(a["url"], headers={**entrega._cab(), "Accept": "application/octet-stream"},
                      stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(destino, "wb") as f:
            for parte in r.iter_content(1 << 20):
                f.write(parte)
    return destino


def enviar_pendentes(est, canal, yt, pasta: Path, horario, log=print) -> int:
    """Sobe os vídeos que ficaram esperando cota (mais antigos primeiro). Devolve quantos subiram."""
    fila = sorted((m for m in est.momentos.values() if m.get("status") == "aguardando_cota"),
                  key=lambda m: m.get("atualizado_em", ""))
    feitos = 0
    for m in fila:
        if not tem_cota(est):
            break
        p = m.get("envio_pendente") or {}
        try:
            pasta.mkdir(parents=True, exist_ok=True)
            video = _baixar_asset(m["video_url"], pasta / f"{m['id']}.mp4")
            capa = _baixar_asset(m["thumb_url"], pasta / f"{m['id']}.jpg") if m.get("thumb_url") else None
        except Exception as e:
            log(f"  pendente {m['id']}: arquivo sumiu ({str(e)[:80]}), descartado")
            est.atualizar(m["id"], status="descartado", motivo="arquivo do envio pendente sumiu")
            continue
        quando = horario()
        if p.get("horario_fixo") and (p.get("publicar_em") or "") > datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"):
            quando = p["publicar_em"]  # vídeo com dia marcado (ex.: contagem regressiva) mantém o horário
        vid = publicar(est, m["id"], yt, video, p.get("titulo") or m.get("titulo", ""), p.get("descricao", ""),
                       p.get("tags") or [], p.get("idioma", canal.idioma), quando, capa, p.get("playlist", ""), log)
        if vid:
            feitos += 1
            log(f"  ✅ envio pendente agendado para {quando}: https://youtu.be/{vid}")
    return feitos
