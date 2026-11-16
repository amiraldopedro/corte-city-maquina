"""Salva a memória da máquina no repositório sem perder nada quando dois trabalhos rodam ao mesmo tempo.

Problema que resolve: a rodada demora ~15 min; se nesse meio tempo um botão do painel mexer no mesmo
estado/br.json, o `git pull --rebase` dá conflito, o push falha e a rodada perde o registro do vídeo
que postou (aí ela postaria o mesmo momento de novo). Aqui a gente junta os dois lados, momento por momento.
"""
from __future__ import annotations

import json
import subprocess
import time

from .config import PASTA_ESTADO, RAIZ
from .estado import gravar_json


def _git(*args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, check=check)


def _quando(m: dict) -> str:
    return max(m.get("atualizado_em") or "", m.get("criado_em") or "")


# ordem natural de um momento: um status "mais adiante" nunca volta para trás por causa de um merge
ORDEM = {"novo": 0, "erro": 1, "pronto": 2, "aguardando_cota": 2, "descartado": 3, "postado": 4, "removido": 5, "manual": 2}
LISTAS = ("usado_em", "clipe_ids", "titulos_chat")


def _juntar_momento(a: dict, b: dict) -> dict:
    """Junta duas versões do mesmo momento campo a campo: a mais nova vence, mas listas somam,
    youtube_id nunca se perde e o status não anda para trás."""
    novo, velho = (a, b) if _quando(a) >= _quando(b) else (b, a)
    m = {**velho, **novo}
    for k in LISTAS:
        if isinstance(a.get(k), list) or isinstance(b.get(k), list):
            m[k] = list(dict.fromkeys((velho.get(k) or []) + (novo.get(k) or [])))
    for k in ("youtube_id", "publicar_em", "postado_em", "video_url"):
        if not m.get(k) and (a.get(k) or b.get(k)):
            m[k] = a.get(k) or b.get(k)
    sa, sb = a.get("status"), b.get("status")
    if ORDEM.get(sa, 0) != ORDEM.get(sb, 0) and novo.get("status") not in ("novo", "removido"):
        m["status"] = sa if ORDEM.get(sa, 0) > ORDEM.get(sb, 0) else sb
    if m.get("youtube_id") and m.get("status") in ("novo", "erro", "pronto", "aguardando_cota"):
        m["status"] = "postado"  # já está no YouTube: jamais volta para a fila
    return m


def juntar_estado(local: dict, remoto: dict) -> dict:
    ms = dict(remoto.get("momentos", {}))
    for mid, m in local.get("momentos", {}).items():
        ms[mid] = _juntar_momento(m, ms[mid]) if mid in ms else m
    vistos = sorted(set(remoto.get("clipes_vistos", [])) | set(local.get("clipes_vistos", [])))
    cota = {**(remoto.get("cota") or {})}
    for dia, n in (local.get("cota") or {}).items():
        cota[dia] = max(n, cota.get(dia, 0))
    return {**remoto, **local, "momentos": ms, "clipes_vistos": vistos[-20000:], "cota": cota}


def sincronizar(mensagem: str, tentativas: int = 6):
    # 1) guarda o que este trabalho produziu
    estados = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in PASTA_ESTADO.glob("*.json")}
    thumbs = {p.name: p.read_bytes() for p in (PASTA_ESTADO / "thumbs").glob("*.jpg")} \
        if (PASTA_ESTADO / "thumbs").exists() else {}
    no_inicio = set(_git("ls-tree", "--name-only", "HEAD", "estado/thumbs/", check=False).stdout.split())
    apagadas = {n.split("/")[-1] for n in no_inicio} - set(thumbs)  # thumbs velhas que este trabalho limpou
    cfg_local = (RAIZ / "config.yaml").read_text(encoding="utf-8")
    cfg_inicio = _git("show", "HEAD:config.yaml", check=False).stdout
    mudou_cfg = cfg_local != cfg_inicio
    _git("config", "user.name", "maquina-de-cortes")
    _git("config", "user.email", "maquina@users.noreply.github.com")

    for i in range(tentativas):
        # 2) pega a versão mais nova do repositório
        if _git("fetch", "-q", "origin", "main", check=False).returncode != 0:
            print(f"fetch falhou (tentativa {i + 1}), tentando de novo…")
            time.sleep(5 + i * 5)
            continue
        _git("reset", "-q", "--hard", "origin/main")
        # 3) junta
        PASTA_ESTADO.mkdir(exist_ok=True)
        for nome, local in estados.items():
            p = PASTA_ESTADO / nome
            remoto = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"momentos": {}, "clipes_vistos": []}
            gravar_json(p, juntar_estado(local, remoto))
        if thumbs:
            (PASTA_ESTADO / "thumbs").mkdir(exist_ok=True)
            for nome, dados in thumbs.items():
                (PASTA_ESTADO / "thumbs" / nome).write_bytes(dados)
        for nome in apagadas:
            (PASTA_ESTADO / "thumbs" / nome).unlink(missing_ok=True)
        if mudou_cfg:
            (RAIZ / "config.yaml").write_text(cfg_local, encoding="utf-8")
        # 4) salva
        _git("add", "estado", "config.yaml")
        if not _git("diff", "--cached", "--quiet", check=False).returncode:
            print("nada para salvar")
            return
        _git("commit", "-qm", f"{mensagem} [skip ci]")
        r = _git("push", "-q", "origin", "HEAD:main", check=False)
        if r.returncode == 0:
            print(f"memória salva ({mensagem})")
            return
        print(f"push recusado (tentativa {i + 1}), juntando de novo…")
        time.sleep(3 + i * 2)
    raise SystemExit("não consegui salvar a memória da máquina depois de várias tentativas")


def salvar_agora(mensagem: str):
    """Salva a memória no repositório no meio da rodada (logo depois de um envio pro YouTube),
    para uma queda do runner nunca fazer a máquina postar o mesmo vídeo de novo. Fora do GitHub, não faz nada."""
    import os
    if os.getenv("GITHUB_ACTIONS") != "true":
        return
    try:
        sincronizar(mensagem, tentativas=3)
    except BaseException as e:  # SystemExit incluso: a rodada continua, o fim do job tenta de novo
        print(f"  aviso: não consegui salvar a memória agora ({str(e)[:120]})")
