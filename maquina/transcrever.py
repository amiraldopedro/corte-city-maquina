"""Transcrição palavra por palavra com faster-whisper (roda local, sem custo)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _modelo(nome: str):
    from faster_whisper import WhisperModel
    return WhisperModel(nome, device="cpu", compute_type="int8",
                        download_root=os.getenv("WHISPER_CACHE") or None)


def _audio(arquivo: Path):
    """Áudio em 16 kHz mono via ffmpeg (evita depender da versão do PyAV, que quebra o faster-whisper)."""
    import subprocess
    import numpy as np
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(arquivo), "-vn", "-ac", "1", "-ar", "16000",
                        "-f", "s16le", "-"], capture_output=True, timeout=600, check=True)
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def transcrever(arquivo: Path, idioma: str, modelo: str = "small") -> list[dict]:
    """Retorna lista de palavras: [{"p": "texto", "i": inicio, "f": fim}, ...]"""
    segmentos, _ = _modelo(modelo).transcribe(
        _audio(arquivo), language=idioma, word_timestamps=True,
        vad_filter=True, beam_size=5,
    )
    palavras = []
    for seg in segmentos:
        for w in seg.words or []:
            texto = w.word.strip()
            if texto:
                palavras.append({"p": texto, "i": round(w.start, 2), "f": round(w.end, 2)})
    return palavras


def texto_com_tempos(palavras: list[dict], passo: float = 3.0) -> str:
    """Formato compacto para a IA: [12.0s] frase... [15.0s] frase..."""
    linhas, atual, marca = [], [], None
    for w in palavras:
        if marca is None:
            marca = w["i"]
        atual.append(w["p"])
        if w["f"] - marca >= passo:
            linhas.append(f"[{marca:.1f}s] {' '.join(atual)}")
            atual, marca = [], None
    if atual:
        linhas.append(f"[{marca:.1f}s] {' '.join(atual)}")
    return "\n".join(linhas)
