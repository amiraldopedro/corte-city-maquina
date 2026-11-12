"""Baixa o trecho REAL da live (VOD da Twitch) com yt-dlp.

Se a VOD não estiver disponível (apagada ou só para inscritos), baixa o clipe do público como plano B.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from .config import PASTA_BRUTOS


def _yt_dlp(args: list[str]) -> None:
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-progress",
           "-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4",
           "--retries", "5", "--fragment-retries", "10", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"yt-dlp falhou: {r.stderr.strip()[-600:]}")


def volume_maximo(arquivo: Path) -> float:
    """Pico de volume em dB (-91 = silêncio total; sem trilha de áudio = -999)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(arquivo), "-vn", "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=600)
    m = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else -999.0


MUDO_DB = -45.0  # abaixo disso o trecho está mudo (a Twitch silencia trechos com música protegida na live gravada)


def baixar_trecho(video_id: str | None, inicio: float, fim: float, clipe_url: str | None, destino: Path) -> Path:
    """Retorna o arquivo. Se teve que usar o clipe no lugar da live, cria `destino.clipe` como marca."""
    marca = destino.with_suffix(".clipe")
    if destino.exists() and destino.stat().st_size > 100_000:
        return destino
    if video_id:
        try:
            _yt_dlp(["--download-sections", f"*{inicio:.1f}-{fim:.1f}", "--force-keyframes-at-cuts",
                     "-o", str(destino), f"https://www.twitch.tv/videos/{video_id}"])
            if destino.exists():
                if volume_maximo(destino) > MUDO_DB or not clipe_url:
                    return destino
                print(f"  trecho da live está mudo (silenciado pela Twitch) — usando o clipe do público")
                destino.unlink()
        except RuntimeError:
            if not clipe_url:
                raise
    if not clipe_url:
        raise RuntimeError("sem VOD e sem clipe para baixar")
    _yt_dlp(["-o", str(destino), clipe_url])
    if not destino.exists():
        raise RuntimeError("download terminou mas o arquivo não apareceu")
    marca.write_text("1")
    if volume_maximo(destino) <= MUDO_DB:
        raise RuntimeError("o clipe também está sem som")
    return destino


def baixar_momento(m: dict) -> Path:
    return baixar_trecho(m.get("video_id"), m["inicio"], m["fim"], m.get("clipe_url"),
                         PASTA_BRUTOS / f"{m['id']}.mp4")
