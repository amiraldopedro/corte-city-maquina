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


def _git(*args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, check=check)


def _quando(m: dict) -> str:
    return max(m.get("atualizado_em") or "", m.get("criado_em") or "")


def juntar_estado(local: dict, remoto: dict) -> dict:
    ms = dict(remoto.get("momentos", {}))
    for mid, m in local.get("momentos", {}).items():
        if mid not in ms or _quando(m) >= _quando(ms[mid]):
            ms[mid] = m
    vistos = sorted(set(remoto.get("clipes_vistos", [])) | set(local.get("clipes_vistos", [])))
    return {**remoto, **local, "momentos": ms, "clipes_vistos": vistos}


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
        _git("fetch", "-q", "origin", "main")
        _git("reset", "-q", "--hard", "origin/main")
        # 3) junta
        PASTA_ESTADO.mkdir(exist_ok=True)
        for nome, local in estados.items():
            p = PASTA_ESTADO / nome
            remoto = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"momentos": {}, "clipes_vistos": []}
            p.write_text(json.dumps(juntar_estado(local, remoto), ensure_ascii=False, indent=1), encoding="utf-8")
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
