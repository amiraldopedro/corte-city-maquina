"""Onde ficam os vídeos (Releases do GitHub).

O código da máquina é público (minutos do GitHub Actions ilimitados), mas os vídeos — brutos de lives,
trailers, clipes de terceiros e os prontos — ficam num repositório PRIVADO só de arquivos.

- ARQUIVOS_REPO (variável do repositório, ex.: amiraldopedro/corte-city-arquivos)
- ARQUIVOS_TOKEN (secret: chave com acesso de escrita aos dois repositórios)

Sem essas duas configuradas, tudo continua no próprio repositório da máquina, como antes.
Baixar por ID tenta o privado primeiro e depois o antigo (os IDs antigos continuam funcionando).
"""
from __future__ import annotations

import os

API = "https://api.github.com"


def privado() -> bool:
    return bool(os.environ.get("ARQUIVOS_REPO") and os.environ.get("ARQUIVOS_TOKEN"))


def repo() -> str:
    return os.environ["ARQUIVOS_REPO"] if privado() else os.environ["GITHUB_REPOSITORY"]


def token() -> str:
    return os.environ["ARQUIVOS_TOKEN"] if privado() else os.environ["GITHUB_TOKEN"]


def cab(binario: bool = False) -> dict:
    return {"Authorization": f"Bearer {token()}",
            "Accept": "application/octet-stream" if binario else "application/vnd.github+json"}


def baixar_asset(asset_id: int, destino, timeout: int = 900):
    """Baixa um arquivo pelo ID, procurando no repositório privado e, se não achar, no da máquina."""
    import json
    from pathlib import Path
    import requests
    mapa = Path(__file__).resolve().parent.parent / "estado" / "mapa_arquivos.json"
    if mapa.exists():  # arquivo que já mudou pro repositório privado: usa o ID novo
        try:
            asset_id = json.loads(mapa.read_text()).get(str(asset_id), asset_id)
        except Exception:
            pass
    tentativas = [(repo(), token())]
    if privado():
        tentativas.append((os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]))
    ultimo = None
    for rp, tk in tentativas:
        r = requests.get(f"{API}/repos/{rp}/releases/assets/{asset_id}", stream=True, timeout=timeout,
                         headers={"Authorization": f"Bearer {tk}", "Accept": "application/octet-stream"})
        if r.status_code == 404:
            ultimo = r
            continue
        r.raise_for_status()
        with open(destino, "wb") as f:
            for parte in r.iter_content(1 << 20):
                f.write(parte)
        return destino
    ultimo.raise_for_status()
