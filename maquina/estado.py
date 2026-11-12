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
        """Insere um momento novo. Se ele cai no mesmo trecho da mesma live de um momento que já existe,
        junta os clipes no existente (ou ignora, se aquele trecho já virou vídeo/foi descartado),
        para nunca fazer dois Shorts da mesma cena."""
        if m["id"] in self.momentos:
            return False
        if m.get("video_id"):
            for x in self.momentos.values():
                if x.get("video_id") == m["video_id"] and m["inicio"] < x["fim"] and x["inicio"] < m["fim"]:
                    if x["status"] == "novo" and not x.get("teste"):
                        from .momentos import JANELA_MAX, _score
                        x["clipe_ids"] = sorted(set(x["clipe_ids"]) | set(m["clipe_ids"]))
                        x["views"] = x.get("views", 0) + m.get("views", 0)
                        x["n_clipes"] = len(x["clipe_ids"])
                        x["titulos_chat"] = (x.get("titulos_chat", []) + m.get("titulos_chat", []))[:8]
                        x["inicio"] = min(x["inicio"], m["inicio"])
                        x["fim"] = min(max(x["fim"], m["fim"]), x["inicio"] + JANELA_MAX)
                        x["score"] = _score(x["views"], x["n_clipes"])
                        x["atualizado_em"] = agora()
                    return False
        m = {**m, "status": "novo", "criado_em": agora()}
        self.momentos[m["id"]] = m
        return True

    def atualizar(self, mid: str, **campos):
        self.momentos[mid].update(campos, atualizado_em=agora())

    def por_status(self, status: str) -> list[dict]:
        lista = [m for m in self.momentos.values() if m["status"] == status]
        return sorted(lista, key=lambda m: (not m.get("prioridade"), -m.get("score", 0)))

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
