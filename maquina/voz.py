"""Isola a voz do streamer (tira a música de fundo) com o Demucs, IA grátis que roda no GitHub.

Usado nos vídeos longos (lá música com direitos autorais derruba o vídeo) e nos Shorts de
react a trailer (a música do trailer faz o YouTube silenciar o Short).
Limite honesto: se a música tiver alguém cantando, um pouco do canto pode ficar junto com a voz.
"""
from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

SR = 44100


def _garantir():
    try:
        import demucs  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        print("  instalando o separador de voz (Demucs)...")
        pip = [sys.executable, "-m", "pip", "install", "-q"]
        subprocess.run(pip + ["--index-url", "https://download.pytorch.org/whl/cpu", "torch", "torchaudio"], check=True)
        subprocess.run(pip + ["demucs"], check=True)
        import importlib
        import site
        importlib.invalidate_caches()  # deixa o Python enxergar o que acabou de instalar
        for pasta in site.getsitepackages():
            if pasta not in sys.path:
                sys.path.append(pasta)


@lru_cache(maxsize=1)
def _modelo():
    _garantir()
    import torch
    from demucs.pretrained import get_model
    torch.set_num_threads(os.cpu_count() or 2)
    m = get_model("htdemucs")
    m.eval()
    return m


def isolar_voz(entrada: Path, saida: Path) -> Path:
    """Gera `saida` com o mesmo vídeo e só a voz. Levanta erro se não conseguir."""
    import torch
    from demucs.apply import apply_model
    modelo = _modelo()
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(entrada), "-vn", "-ac", "2", "-ar", str(SR),
                        "-f", "f32le", "-"], capture_output=True, timeout=900, check=True)
    audio = np.frombuffer(r.stdout, dtype=np.float32).reshape(-1, 2).T.copy()
    if audio.shape[1] < SR:
        raise RuntimeError("áudio curto demais para separar")
    wav = torch.from_numpy(audio)
    ref = wav.mean(0)
    media, desvio = ref.mean(), ref.std() + 1e-8
    with torch.no_grad():
        fontes = apply_model(modelo, ((wav - media) / desvio)[None], device="cpu", split=True,
                             overlap=0.1, progress=False)[0]
    voz = fontes[modelo.sources.index("vocals")] * desvio + media
    pcm = voz.T.contiguous().numpy().astype(np.float32).tobytes()
    p = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(entrada),
                        "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "pipe:0",
                        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                        "-shortest", str(saida)], input=pcm, capture_output=True, timeout=900)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg (voz): {p.stderr.decode()[-400:]}")
    return saida


def tentar_isolar(bruto: Path) -> Path | None:
    """Versão com voz isolada ao lado do bruto (reaproveita se já existir). None se falhar."""
    destino = bruto.with_name(bruto.stem + ".voz.mp4")
    if destino.exists():
        return destino
    try:
        return isolar_voz(bruto, destino)
    except Exception as e:
        print(f"  ⚠️ não consegui isolar a voz de {bruto.name}: {str(e)[:200]}")
        return None
