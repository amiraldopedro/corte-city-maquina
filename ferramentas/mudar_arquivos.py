"""Muda os vídeos das Releases do repositório público (máquina) pro repositório privado de arquivos.

1. Copia cada arquivo (sem baixar tudo de uma vez: um por vez, em streaming) pra mesma "tag" no privado.
2. Troca os IDs/links antigos pelos novos na memória da máquina (estado/*.json).
3. Só depois apaga a cópia pública daquele arquivo.

Pode rodar de novo à vontade: o que já foi copiado é pulado.
Uso (no GitHub Actions): ARQUIVOS_REPO, ARQUIVOS_TOKEN, GITHUB_REPOSITORY e GITHUB_TOKEN no ambiente.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import requests

API = "https://api.github.com"
PUB, PUB_TK = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
PRIV, PRIV_TK = os.environ.get("ARQUIVOS_REPO", ""), os.environ.get("ARQUIVOS_TOKEN", "")
APAGAR = os.environ.get("APAGAR_PUBLICO", "sim") == "sim"
RAIZ = Path(__file__).resolve().parent.parent


def h(tk, bin_=False):
    return {"Authorization": f"Bearer {tk}", "Accept": "application/octet-stream" if bin_ else "application/vnd.github+json"}


def todas_releases(repo, tk):
    saida, p = [], 1
    while True:
        r = requests.get(f"{API}/repos/{repo}/releases?per_page=50&page={p}", headers=h(tk), timeout=60)
        r.raise_for_status()
        lote = r.json()
        if not lote:
            return saida
        saida += lote
        p += 1


def assets(repo, tk, rid):
    saida, p = [], 1
    while True:
        r = requests.get(f"{API}/repos/{repo}/releases/{rid}/assets?per_page=100&page={p}", headers=h(tk), timeout=60)
        r.raise_for_status()
        lote = r.json()
        if not lote:
            return saida
        saida += lote
        p += 1


def release_priv(rel_pub):
    r = requests.get(f"{API}/repos/{PRIV}/releases/tags/{rel_pub['tag_name']}", headers=h(PRIV_TK), timeout=60)
    if r.status_code == 200:
        return r.json()
    r = requests.post(f"{API}/repos/{PRIV}/releases", headers=h(PRIV_TK), timeout=60,
                      json={"tag_name": rel_pub["tag_name"], "name": rel_pub.get("name") or rel_pub["tag_name"],
                            "body": rel_pub.get("body") or "", "prerelease": bool(rel_pub.get("prerelease"))})
    if r.status_code == 422:  # repositório vazio: precisa de um commit antes de criar tag
        requests.put(f"{API}/repos/{PRIV}/contents/README.md", headers=h(PRIV_TK), timeout=60, json={
            "message": "Arquivos da máquina Corte City",
            "content": "IyBBcnF1aXZvcyBkYSBtw6FxdWluYSBDb3J0ZSBDaXR5CgpWw61kZW9zIGd1YXJkYWRvcyBwZWxhIG3DoXF1aW5hIChwcml2YWRvKS4K"})
        r = requests.post(f"{API}/repos/{PRIV}/releases", headers=h(PRIV_TK), timeout=60,
                          json={"tag_name": rel_pub["tag_name"], "name": rel_pub.get("name") or rel_pub["tag_name"],
                                "body": rel_pub.get("body") or "", "prerelease": bool(rel_pub.get("prerelease"))})
    r.raise_for_status()
    return r.json()


def copiar(a, rel_priv, ja):
    if a["name"] in ja and ja[a["name"]]["size"] == a["size"]:
        return ja[a["name"]]
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        with requests.get(a["url"], headers=h(PUB_TK, True), stream=True, timeout=900) as r:
            r.raise_for_status()
            for parte in r.iter_content(1 << 20):
                tmp.write(parte)
    try:
        if a["name"] in ja:  # cópia quebrada de uma tentativa anterior
            requests.delete(f"{API}/repos/{PRIV}/releases/assets/{ja[a['name']]['id']}", headers=h(PRIV_TK), timeout=60)
        with open(tmp.name, "rb") as f:
            r = requests.post(f"https://uploads.github.com/repos/{PRIV}/releases/{rel_priv['id']}/assets",
                              params={"name": a["name"]}, data=f, timeout=1800,
                              headers={**h(PRIV_TK), "Content-Type": a.get("content_type") or "application/octet-stream"})
        r.raise_for_status()
        return r.json()
    finally:
        os.unlink(tmp.name)


def _campo_de_arquivo(chave) -> bool:
    return isinstance(chave, str) and (chave == "asset_id" or chave.endswith("_asset") or chave == "asset")


def trocar(obj, mapa_id, mapa_url, chave=None):
    """Troca IDs (só em campos de arquivo: yt_asset, asset_id, video_asset...) e links antigos pelos novos."""
    if isinstance(obj, dict):
        return {k: trocar(v, mapa_id, mapa_url, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [trocar(v, mapa_id, mapa_url, chave) for v in obj]
    if isinstance(obj, str) and obj in mapa_url:
        return mapa_url[obj]
    if _campo_de_arquivo(chave):
        if isinstance(obj, int) and not isinstance(obj, bool) and obj in mapa_id:
            return mapa_id[obj]
        if isinstance(obj, str) and obj.isdigit() and int(obj) in mapa_id:
            return str(mapa_id[int(obj)])
    return obj


def main():
    if not (PRIV and PRIV_TK):
        sys.exit("Falta configurar ARQUIVOS_REPO (variável) e ARQUIVOS_TOKEN (secret).")
    r = requests.get(f"{API}/repos/{PRIV}", headers=h(PRIV_TK), timeout=60)
    if r.status_code != 200 or not r.json().get("private"):
        sys.exit(f"Não abri {PRIV} como repositório privado ({r.status_code}). Confira o nome e a chave.")
    mapa_id, mapa_url, copiados = {}, {}, []
    for rel in todas_releases(PUB, PUB_TK):
        lista = assets(PUB, PUB_TK, rel["id"])
        if not lista:
            continue
        priv = release_priv(rel)
        ja = {a["name"]: a for a in assets(PRIV, PRIV_TK, priv["id"])}
        print(f"== {rel['tag_name']}: {len(lista)} arquivos", flush=True)
        for n, a in enumerate(lista, 1):
            try:
                novo = copiar(a, priv, ja)
            except Exception as e:
                print(f"  ❌ {a['name']}: {str(e)[:120]}", flush=True)
                continue
            mapa_id[a["id"]] = novo["id"]
            mapa_url[a["browser_download_url"]] = novo["browser_download_url"]
            copiados.append(a)
            if n % 25 == 0:
                print(f"  {n}/{len(lista)}", flush=True)
    # memória da máquina: IDs e links novos
    for arq in sorted((RAIZ / "estado").glob("*.json")):
        d = json.loads(arq.read_text())
        novo = trocar(d, mapa_id, mapa_url)
        from datetime import datetime, timezone
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for mid, m in (novo.get("momentos") or {}).items():  # marca como mais novo pra vencer o merge
            if m != (d.get("momentos") or {}).get(mid):
                m["atualizado_em"] = agora
        if novo != d:
            arq.write_text(json.dumps(novo, ensure_ascii=False, indent=1))
            print(f"  memória atualizada: {arq.name}")
    (RAIZ / "estado" / "mapa_arquivos.json").write_text(json.dumps({str(k): v for k, v in mapa_id.items()}, indent=0))
    print(f"copiados: {len(copiados)}", flush=True)
    if APAGAR:
        for a in copiados:
            requests.delete(f"{API}/repos/{PUB}/releases/assets/{a['id']}", headers=h(PUB_TK), timeout=60)
        print(f"apagados do público: {len(copiados)}")


if __name__ == "__main__":
    main()
