"""Ações que o painel visual dispara (pelo workflow "Painel - ação") e números para ele mostrar."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import PASTA_ESTADO, RAIZ, Config
from .estado import Estado, agora

PASTA_THUMBS = PASTA_ESTADO / "thumbs"
DIAS_THUMB = 45


# ---------------------------------------------------------------- thumbs
def guardar_thumb(origem: Path, momento_id: str):
    """Cópia pequena da thumb no repositório, para o painel mostrar (vídeo privado não tem thumb pública)."""
    from PIL import Image
    PASTA_THUMBS.mkdir(parents=True, exist_ok=True)
    img = Image.open(origem).convert("RGB")
    img.thumbnail((480, 480))
    img.save(PASTA_THUMBS / f"{momento_id}.jpg", "JPEG", quality=78)


def limpar_thumbs():
    if not PASTA_THUMBS.exists():
        return
    limite = datetime.now().timestamp() - DIAS_THUMB * 86400
    for f in PASTA_THUMBS.glob("*.jpg"):
        if f.stat().st_mtime < limite:
            f.unlink()


# ---------------------------------------------------------------- números
def atualizar_numeros(cfg: Config):
    """Busca views, likes e status de cada vídeo postado nos últimos 60 dias (custa quase nada de cota)."""
    from .youtube import YouTube
    desde = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(timespec="seconds")
    for canal in cfg.canais:
        if not canal.refresh_token:
            continue
        est = Estado(canal.id)
        alvos = {m["youtube_id"]: m for m in est.momentos.values()
                 if m.get("youtube_id") and m["status"] == "postado" and m.get("postado_em", "") >= desde}
        if not alvos:
            continue
        try:
            yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token)
            ids = list(alvos)
            vistos = set()
            for i in range(0, len(ids), 50):
                r = yt.yt.videos().list(part="statistics,status", id=",".join(ids[i:i + 50])).execute()
                for v in r.get("items", []):
                    s, st = v.get("statistics", {}), v.get("status", {})
                    alvos[v["id"]].update(views=int(s.get("viewCount", 0)), likes=int(s.get("likeCount", 0)),
                                          comentarios=int(s.get("commentCount", 0)),
                                          privacidade=st.get("privacyStatus"), publicar_em=st.get("publishAt"),
                                          numeros_em=agora())
                    vistos.add(v["id"])
            for vid in set(ids) - vistos:  # sumiu do YouTube (você apagou no Studio, ou foi removido)
                alvos[vid].update(status="removido", numeros_em=agora())
            est.salvar()
            print(f"  números de {canal.nome}: {len(vistos)} vídeos atualizados")
        except Exception as e:
            print(f"  números de {canal.nome}: falhou ({str(e)[:150]})")


# ---------------------------------------------------------------- config.yaml
def _ler_config() -> str:
    return (RAIZ / "config.yaml").read_text(encoding="utf-8")


def _gravar_config(texto: str):
    (RAIZ / "config.yaml").write_text(texto, encoding="utf-8")


def _lista_bloqueados(texto: str) -> list[str]:
    m = re.search(r"^bloqueados:\s*\[(.*?)\]\s*$", texto, re.M)
    return [x.strip().strip("\"'") for x in m.group(1).split(",") if x.strip()] if m else []


def _salvar_bloqueados(texto: str, lista: list[str]) -> str:
    nova = "bloqueados: [" + ", ".join(lista) + "]"
    if re.search(r"^bloqueados:.*$", texto, re.M):
        return re.sub(r"^bloqueados:.*$", nova, texto, flags=re.M)
    return texto.rstrip() + "\n" + nova + "\n"


def bloquear(login: str):
    login = login.lower().strip()
    t = _ler_config()
    lista = _lista_bloqueados(t)
    if login and login not in lista:
        lista.append(login)
    _gravar_config(_salvar_bloqueados(t, lista))
    print(f"{login} bloqueado")


def desbloquear(login: str):
    login = login.lower().strip()
    t = _ler_config()
    _gravar_config(_salvar_bloqueados(t, [x for x in _lista_bloqueados(t) if x != login]))
    print(f"{login} desbloqueado")


def adicionar_streamer(canal_id: str, login: str, nome: str):
    login = re.sub(r"[^a-z0-9_]", "", login.lower().strip())
    nome = (nome or login).replace('"', "").strip()
    if not login:
        raise SystemExit("login vazio")
    linhas = _ler_config().split("\n")
    dentro, inserir_em = False, None
    for i, l in enumerate(linhas):
        if re.match(r"^\s*- id:\s*", l):
            dentro = l.split(":", 1)[1].strip() == canal_id
        if dentro and re.match(r"^\s*- \{ login:\s*" + re.escape(login) + r"\b", l):
            print(f"{login} já está no canal {canal_id}")
            return
        if dentro and re.match(r"^\s{4}streamers:\s*$", l):
            inserir_em = i + 1
            while inserir_em < len(linhas) and (linhas[inserir_em].strip().startswith("- {")
                                                 or linhas[inserir_em].strip().startswith("#")):
                inserir_em += 1
    if inserir_em is None:
        raise SystemExit(f"canal {canal_id} não encontrado no config.yaml")
    linhas.insert(inserir_em, f'      - {{ login: {login}, nome: "{nome}" }}')
    _gravar_config("\n".join(linhas))
    print(f"{nome} ({login}) adicionado ao canal {canal_id}")


def remover_streamer(canal_id: str, login: str):
    login = login.lower().strip()
    linhas, dentro, saida = _ler_config().split("\n"), False, []
    for l in linhas:
        if re.match(r"^\s*- id:\s*", l):
            dentro = l.split(":", 1)[1].strip() == canal_id
        if dentro and re.match(r"^\s*- \{ login:\s*" + re.escape(login) + r"\b", l):
            continue
        saida.append(l)
    _gravar_config("\n".join(saida))
    print(f"{login} removido do canal {canal_id}")


# ---------------------------------------------------------------- vídeos
def _achar(cfg: Config, mid: str):
    for canal in cfg.canais:
        est = Estado(canal.id)
        if mid in est.momentos:
            return canal, est, est.momentos[mid]
    raise SystemExit(f"momento {mid} não encontrado")


def marcar_postado(cfg: Config, mid: str, link: str = ""):
    """Você postou o vídeo no YouTube: ele sai de "prontos". O link (opcional) deixa o painel mostrar as views."""
    canal, est, m = _achar(cfg, mid)
    yid = None
    if link:
        r = re.search(r"(?:youtu\.be/|v=|shorts/|/video/)([A-Za-z0-9_-]{11})", link) or re.fullmatch(r"([A-Za-z0-9_-]{11})", link.strip())
        yid = r.group(1) if r else None
    est.atualizar(mid, status="postado", postado_em=agora(), **({"youtube_id": yid} if yid else {}))
    est.salvar()
    from .entrega import apagar_arquivo
    apagar_arquivo(m.get("video_asset"))  # o vídeo já está no YouTube: libera espaço
    print(f"{mid}: marcado como postado{' (' + yid + ')' if yid else ''}")


def descartar(cfg: Config, mid: str):
    """Momento na fila: sai da fila. Vídeo já enviado: é apagado do YouTube."""
    canal, est, m = _achar(cfg, mid)
    if m.get("youtube_id") and m["status"] == "postado" and canal.refresh_token:
        from .youtube import YouTube
        YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token).apagar(m["youtube_id"])
    if m["status"] == "pronto":
        from .entrega import apagar_arquivo
        apagar_arquivo(m.get("video_asset"))
        apagar_arquivo(m.get("thumb_asset"))
    est.atualizar(mid, status="descartado", motivo="descartado no painel")
    est.salvar()
    print(f"{mid}: descartado")


def priorizar(cfg: Config, mid: str):
    canal, est, m = _achar(cfg, mid)
    est.atualizar(mid, prioridade=True, status="novo" if m["status"] in ("erro", "descartado") else m["status"])
    est.salvar()
    print(f"{mid}: vai ser o próximo da fila")
