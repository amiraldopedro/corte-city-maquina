"""Vídeos longos horizontais (1920x1080): "Melhores do Dia" e "Top 10 da Semana".

Cada momento entra inteiro (com contexto), com o nome do streamer no canto
e, no Top 10, o número grande da posição. Os trechos são baixados de novo
direto da VOD, porque o GitHub Actions não guarda arquivos entre rodadas.
"""
from __future__ import annotations

from pathlib import Path

from .baixar import baixar_trecho
from .config import FONTES, PASTA_BRUTOS, PASTA_PRONTOS
from .editar import _escapar, rodar

W, H = 1920, 1080


def _texto(t: str) -> str:
    return t.replace("\\", "").replace("'", "’").replace(":", "\\:").replace("%", "\\%")


def _segmento(bruto: Path, destino: Path, nome: str, numero: int | None, cor: str, marca: Path | None):
    fonte = _escapar(FONTES / "Anton-Regular.ttf")
    cor_ff = "0x" + cor.lstrip("#")
    filtro = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
              f"setsar=1,fps=30,"
              f"drawtext=fontfile='{fonte}':text='{_texto(nome.upper())}':x=60:y=h-140:fontsize=64:"
              f"fontcolor=white:box=1:boxcolor=0xFF3B4E@1:boxborderw=18")
    if numero is not None:
        filtro += (f",drawtext=fontfile='{fonte}':text='#{numero}':x=60:y=40:fontsize=170:fontcolor={cor_ff}:"
                   f"borderw=10:bordercolor=black")
    entradas = ["-i", str(bruto)]
    if marca and Path(marca).exists():
        entradas += ["-i", str(marca)]
        filtro += "[v0];[1:v]scale=150:-1,format=rgba,colorchannelmixer=aa=0.8[m];[v0][m]overlay=W-w-40:H-h-40,format=yuv420p[v]"
    else:
        filtro += ",format=yuv420p[v]"
    rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", filtro, "-map", "[v]",
           "-map", "0:a?", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "160k",
           "-ac", "2", str(destino)])


def _duracao(arquivo: Path) -> float:
    import subprocess
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(arquivo)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def montar(momentos: list[dict], nomes: dict[str, str], tipo: str, cor: str, marca: Path | None,
           saida: Path, minimo: int = 3) -> list[dict]:
    """momentos já ordenados na ordem em que devem aparecer. Retorna os que entraram,
    cada um com `_cap` = segundo em que começa no vídeo (para os capítulos da descrição).

    Vídeo longo NUNCA vai com a música original: a voz é isolada em cada trecho e,
    se não der para isolar, o trecho fica de fora."""
    from .voz import tentar_isolar
    pasta = PASTA_PRONTOS / f"comp_{saida.stem}"
    pasta.mkdir(parents=True, exist_ok=True)
    partes, usados = [], []
    total = len(momentos)
    relogio = 0.0
    for i, m in enumerate(momentos):
        try:
            bruto = baixar_trecho(m.get("video_id"), m["inicio"], m["fim"], m.get("clipe_url"),
                                  PASTA_BRUTOS / f"{m['id']}.mp4")
            voz = tentar_isolar(bruto)
            if not voz:
                raise RuntimeError("sem voz isolada (não entra com música)")
            parte = pasta / f"{i:02d}.mp4"
            numero = (total - i) if tipo == "top10" else None
            _segmento(voz, parte, nomes.get(m["streamer"], m.get("nome") or m["streamer"]), numero, cor, marca)
            partes.append(parte)
            usados.append({**m, "_cap": relogio})
            relogio += _duracao(parte)
        except Exception as e:
            print(f"  compilado: pulei {m['id']} ({str(e)[:150]})")
    if len(partes) < minimo:
        raise RuntimeError("poucos momentos para montar o compilado")
    lista = pasta / "lista.txt"
    lista.write_text("".join(f"file '{p.resolve()}'\n" for p in partes))
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lista),
           "-c", "copy", "-movflags", "+faststart", str(saida)])
    return usados
