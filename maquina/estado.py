"""Memória da máquina: um JSON por canal salvo no próprio repositório (estado/<canal>.json).

Cada momento passa pelas etapas:
  novo -> pronto -> postado     (ou descartado / erro)
Assim a máquina nunca corta o mesmo trecho duas vezes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .config import PASTA_ESTADO

MAX_GUARDADOS = 3000  # momentos antigos descartados saem do arquivo para ele não crescer sem fim


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Estado:
    def __init__(self, canal_id: str):
        self.caminho = PASTA_ESTADO / f"{canal_id}.json"
        if self.caminho.exists():
            self.dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        else:
            self.dados = {"momentos": {}, "clipes_vistos": []}
        self._vistos = set(self.dados["clipes_vistos"])

    # ---------- clipes ----------
    def clipe_visto(self, clipe_id: str) -> bool:
        return clipe_id in self._vistos

    def marcar_clipes(self, ids):
        self._vistos.update(ids)

    # ---------- momentos ----------
    @property
    def momentos(self) -> dict:
        return self.dados["momentos"]

    def inserir(self, m: dict) -> bool:
        if m["id"] in self.momentos:
            return False
        m = {**m, "status": "novo", "criado_em": agora()}
        self.momentos[m["id"]] = m
        return True

    def atualizar(self, mid: str, **campos):
        self.momentos[mid].update(campos, atualizado_em=agora())

    def por_status(self, status: str) -> list[dict]:
        lista = [m for m in self.momentos.values() if m["status"] == status]
        return sorted(lista, key=lambda m: -m.get("score", 0))

    def do_streamer(self, login: str) -> list[dict]:
        return [m for m in self.momentos.values() if m["streamer"] == login]

    def postados_desde(self, desde_iso: str, tipo: str = "short") -> list[dict]:
        return [m for m in self.momentos.values()
                if m["status"] == "postado" and m.get("tipo", "short") == tipo
                and m.get("postado_em", "") >= desde_iso]

    # ---------- salvar ----------
    def salvar(self):
        ms = self.momentos
        if len(ms) > MAX_GUARDADOS:
            velhos = sorted((m for m in ms.values() if m["status"] in ("descartado", "erro")),
                            key=lambda m: m.get("criado_em", ""))
            for m in velhos[: len(ms) - MAX_GUARDADOS]:
                ms.pop(m["id"], None)
        self.dados["clipes_vistos"] = sorted(self._vistos)[-20000:]
        self.caminho.write_text(json.dumps(self.dados, ensure_ascii=False, indent=1), encoding="utf-8")
