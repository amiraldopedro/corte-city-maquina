"""Envio manual: posta pela máquina vídeos que foram editados fora dela (ex.: pelo Claude no chat).

Os arquivos chegam num branch temporário (envio-manual) com um envio/pedido.json. Para cada item:
1. junta as partes do vídeo (arquivos grandes vêm picados em partes < 100 MB) e confere o md5;
2. guarda vídeo e thumb nos downloads (Releases "prontos"), igual aos vídeos da máquina;
3. registra o momento no estado do canal e agenda no YouTube pelo mesmo caminho de sempre
   (maquina.publicar: nunca posta duas vezes, respeita a cota e, sem cota, fica "aguardando_cota").

Uso: python ferramentas/envio_manual.py <pasta do branch envio-manual>
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from maquina import entrega  # noqa: E402
from maquina.config import carregar  # noqa: E402
from maquina.estado import Estado, agora  # noqa: E402
from maquina.publicar import publicar  # noqa: E402
from maquina.youtube import YouTube  # noqa: E402


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def main(pasta_branch: str):
    base = Path(pasta_branch) / "envio"
    pedido = json.loads((base / "pedido.json").read_text(encoding="utf-8"))
    cfg = carregar()
    canal = next(c for c in cfg.canais if c.id == pedido.get("canal", "br"))
    est = Estado(canal.id)
    yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token)
    for it in pedido["itens"]:
        mid = it["id"]
        print(f"== {mid}")
        m = est.momentos.get(mid)
        if m and m.get("youtube_id"):
            print(f"   já está no YouTube: https://youtu.be/{m['youtube_id']}")
            continue
        video = base / it["arquivo"]
        if it.get("partes"):
            with open(video, "wb") as saida:
                for parte in it["partes"]:
                    saida.write((base / parte).read_bytes())
        if it.get("md5") and _md5(video) != it["md5"]:
            raise SystemExit(f"   {video.name}: md5 não confere, arquivo corrompido")
        capa = base / it["thumb"] if it.get("thumb") else None
        if not (m and m.get("video_url")):
            v = entrega.enviar_arquivo(video, f"{mid}.mp4", "video/mp4")
            t = entrega.enviar_arquivo(capa, f"{mid}.jpg", "image/jpeg") if capa else {}
            arquivos = {"video_url": v["url"], "video_asset": v["id"],
                        "thumb_url": t.get("url"), "thumb_asset": t.get("id")}
        else:
            arquivos = {}
        if mid not in est.momentos:
            est.momentos[mid] = {"id": mid, "canal": canal.id, "status": "pronto", "criado_em": agora(),
                                 "manual": True, "views": 0, "n_clipes": 0, "score": 0, "prioridade": False}
        est.atualizar(mid, tipo=it.get("tipo", "short"), streamer=it.get("streamer", ""), nome=it.get("nome", ""),
                      plataforma=it.get("plataforma", ""), jogo=it.get("jogo", ""), quadro=it.get("quadro", ""),
                      titulo=it["titulo"], gancho=it.get("gancho", ""), descricao=it["descricao"],
                      tags=it.get("tags", []), feito_em=agora(), **arquivos)
        est.salvar()
        playlist = canal.playlists.get(it.get("playlist", ""), "")
        vid = publicar(est, mid, yt, video, it["titulo"], it["descricao"], it.get("tags", []), canal.idioma,
                       it.get("publicar_em"), capa, playlist, print, horario_fixo=True)
        if vid:
            print(f"   ✅ agendado para {it.get('publicar_em')}: https://youtu.be/{vid}")
        else:
            print("   ⏸️  ficou aguardando cota: o workflow 'Envios pendentes' sobe depois")
    est.salvar()


if __name__ == "__main__":
    main(sys.argv[1])
