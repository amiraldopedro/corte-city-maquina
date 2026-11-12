"""Cliente mínimo da API Helix da Twitch (token de app, sem login de usuário)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import requests

API = "https://api.twitch.tv/helix"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"


class Twitch:
    def __init__(self, client_id: str, client_secret: str):
        if not client_id or not client_secret:
            raise SystemExit("Faltou TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET nos Secrets do GitHub")
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None
        self._expira = 0.0
        self.sessao = requests.Session()

    # ---------- autenticação ----------
    def _cabecalhos(self) -> dict:
        if not self._token or time.time() > self._expira - 60:
            r = self.sessao.post(TOKEN_URL, data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            }, timeout=20)
            r.raise_for_status()
            dados = r.json()
            self._token = dados["access_token"]
            self._expira = time.time() + dados.get("expires_in", 3600)
        return {"Client-Id": self.client_id, "Authorization": f"Bearer {self._token}"}

    def _get(self, rota: str, params) -> dict:
        for tentativa in range(4):
            r = self.sessao.get(f"{API}/{rota}", headers=self._cabecalhos(), params=params, timeout=30)
            if r.status_code == 429:  # limite de requisições: espera e tenta de novo
                espera = max(1, int(r.headers.get("Ratelimit-Reset", time.time() + 5)) - int(time.time()))
                time.sleep(min(espera, 30))
                continue
            if r.status_code == 401 and tentativa == 0:
                self._token = None
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return {}

    # ---------- consultas ----------
    def usuarios(self, logins: list[str]) -> dict[str, dict]:
        """login -> dados do usuário (inclui 'id')."""
        resultado = {}
        for i in range(0, len(logins), 100):
            lote = logins[i:i + 100]
            dados = self._get("users", [("login", l) for l in lote])
            for u in dados.get("data", []):
                resultado[u["login"].lower()] = u
        return resultado

    def ids_jogos(self, nomes: list[str]) -> dict[str, str]:
        """game_id -> nome do jogo (só os que existem na Twitch)."""
        dados = self._get("games", [("name", n) for n in nomes])
        return {g["id"]: g["name"] for g in dados.get("data", [])}

    def ao_vivo(self, ids_usuarios: list[str]) -> dict[str, dict]:
        dados = self._get("streams", [("user_id", u) for u in ids_usuarios][:100])
        return {s["user_id"]: s for s in dados.get("data", [])}

    def clipes(self, broadcaster_id: str = "", horas: int = 24, maximo: int = 300, game_id: str = "") -> list[dict]:
        """Clipes criados nas últimas `horas`, os mais vistos primeiro (ordem da própria API).
        Com game_id: os clipes mais vistos daquele jogo, de qualquer streamer."""
        fim = datetime.now(timezone.utc)
        inicio = fim - timedelta(hours=horas)
        params = {
            **({"game_id": game_id} if game_id else {"broadcaster_id": broadcaster_id}),
            "started_at": inicio.isoformat().replace("+00:00", "Z"),
            "ended_at": fim.isoformat().replace("+00:00", "Z"),
            "first": 100,
        }
        todos: list[dict] = []
        while len(todos) < maximo:
            dados = self._get("clips", params)
            todos.extend(dados.get("data", []))
            cursor = dados.get("pagination", {}).get("cursor")
            if not cursor or not dados.get("data"):
                break
            params["after"] = cursor
        return todos
