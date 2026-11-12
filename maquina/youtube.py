"""Envio para o YouTube (API oficial), playlists e remoção de vídeos."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

ESCOPOS = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]


class YouTube:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        if not (client_id and client_secret and refresh_token):
            raise RuntimeError("faltam YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN_<CANAL> nos Secrets")
        cred = Credentials(None, refresh_token=refresh_token, client_id=client_id, client_secret=client_secret,
                           token_uri="https://oauth2.googleapis.com/token", scopes=ESCOPOS)
        self.yt = build("youtube", "v3", credentials=cred, cache_discovery=False)
        self._playlists: dict[str, str] | None = None

    def nome_do_canal(self) -> str:
        r = self.yt.channels().list(part="snippet", mine=True).execute()
        return r["items"][0]["snippet"]["title"] if r.get("items") else "?"

    def enviar(self, video: Path, titulo: str, descricao: str, tags: list[str], idioma: str,
               publicar_em: str | None, thumb: Path | None = None) -> str:
        lingua = "pt-BR" if idioma == "pt" else "en-US"
        status = {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
        if publicar_em:
            status["publishAt"] = publicar_em
        corpo = {"snippet": {"title": titulo[:100], "description": descricao[:5000], "tags": tags[:30],
                             "categoryId": "20", "defaultLanguage": lingua, "defaultAudioLanguage": lingua},
                 "status": status}
        req = self.yt.videos().insert(part="snippet,status", body=corpo,
                                      media_body=MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True))
        resp, tentativas = None, 0
        while resp is None:
            try:
                _, resp = req.next_chunk()
            except HttpError as e:
                tentativas += 1
                if e.resp.status in (500, 502, 503, 504) and tentativas < 5:
                    time.sleep(5 * tentativas)
                    continue
                raise
        vid = resp["id"]
        if thumb and Path(thumb).exists():
            try:
                self.yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
            except HttpError as e:  # canal sem verificação por telefone não aceita thumb personalizada
                print(f"  aviso: thumbnail não aplicada ({str(e)[:120]})")
        return vid

    # ---------- playlists ----------
    def _carregar_playlists(self) -> dict[str, str]:
        if self._playlists is None:
            self._playlists, token = {}, None
            while True:
                r = self.yt.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=token).execute()
                for p in r.get("items", []):
                    self._playlists[p["snippet"]["title"].strip().lower()] = p["id"]
                token = r.get("nextPageToken")
                if not token:
                    break
        return self._playlists

    def por_na_playlist(self, video_id: str, nome_playlist: str):
        if not nome_playlist:
            return
        pid = self._carregar_playlists().get(nome_playlist.strip().lower())
        if not pid:
            print(f"  aviso: playlist '{nome_playlist}' não existe no canal")
            return
        try:
            self.yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
        except HttpError as e:
            print(f"  aviso: não entrou na playlist ({str(e)[:120]})")

    def apagar(self, video_id: str) -> bool:
        try:
            self.yt.videos().delete(id=video_id).execute()
            return True
        except HttpError as e:
            print(f"  não consegui apagar {video_id}: {str(e)[:120]}")
            return False


def proximo_horario(horarios: list[str], fuso: str, ocupados: set[str]) -> str:
    """Próximo horário livre da grade (em UTC ISO), começando daqui a pelo menos 1 hora."""
    tz = ZoneInfo(fuso)
    agora = datetime.now(tz)
    for dia in range(0, 14):
        data = (agora + timedelta(days=dia)).date()
        for h in sorted(horarios):
            hh, mm = map(int, h.split(":"))
            quando = datetime(data.year, data.month, data.day, hh, mm, tzinfo=tz)
            iso = quando.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
            if quando > agora + timedelta(hours=1) and iso not in ocupados:
                return iso
    raise RuntimeError("agenda cheia pelos próximos 14 dias")
