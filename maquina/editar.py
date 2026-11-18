"""Edição do Short vertical (1080x1920).

Layout automático:
  * Achou a webcam do streamer -> webcam em cima, jogo embaixo.
  * Não achou (ou a câmera ocupa a tela toda) -> jogo inteiro no meio com o
    mesmo vídeo desfocado de fundo.
Legenda grande palavra por palavra, marca d'água do canal e áudio normalizado.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np

from .config import FONTES
from . import marca as M

W, H = 1080, 1920
TOPO_H = 640                 # altura da faixa da webcam
JOGO_H = H - TOPO_H          # 1280


# ---------------------------------------------------------------- utilidades
def rodar(cmd: list[str], timeout: int = 1800):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {r.stderr.strip()[-900:]}")


def info_video(arquivo: Path) -> tuple[int, int, float]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:format=duration", "-of", "default=nw=1", str(arquivo)],
                       capture_output=True, text=True, check=True)
    d = dict(l.split("=") for l in r.stdout.split() if "=" in l)
    return int(d["width"]), int(d["height"]), float(d.get("duration", 0) or 0)


def frame_em(arquivo: Path, segundo: float) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(arquivo))
    cap.set(cv2.CAP_PROP_POS_MSEC, segundo * 1000)
    ok, img = cap.read()
    cap.release()
    return img if ok else None


# ---------------------------------------------------------------- webcam
def achar_webcam(arquivo: Path, inicio: float, fim: float) -> dict | None:
    """Procura um rosto que fica parado no mesmo lugar (a webcam sobreposta ao jogo).

    Retorna a região da webcam (x, y, l, a em pixels) ou None.
    """
    xml = Path(getattr(getattr(cv2, "data", None), "haarcascades", "")) / "haarcascade_frontalface_default.xml"
    if not xml.exists():
        print("  aviso: detector de rosto indisponível, usando layout com fundo desfocado")
        return None
    detector = cv2.CascadeClassifier(str(xml))
    largura, altura, _ = info_video(arquivo)
    achados = []
    tempos = np.linspace(inicio + 1, max(inicio + 1.5, fim - 1), 8)
    for t in tempos:
        img = frame_em(arquivo, float(t))
        if img is None:
            continue
        cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        rostos = detector.detectMultiScale(cinza, scaleFactor=1.1, minNeighbors=6,
                                           minSize=(int(altura * 0.06), int(altura * 0.06)))
        for (x, y, l, a) in rostos:
            achados.append((x + l / 2, y + a / 2, l))
    if len(achados) < 3:
        return None
    # agrupa rostos que aparecem quase no mesmo lugar
    melhor = []
    for cx, cy, l in achados:
        grupo = [r for r in achados if abs(r[0] - cx) < l * 0.6 and abs(r[1] - cy) < l * 0.6]
        if len(grupo) > len(melhor):
            melhor = grupo
    if len(melhor) < 3:
        return None
    cx = float(np.median([r[0] for r in melhor]))
    cy = float(np.median([r[1] for r in melhor]))
    l = float(np.median([r[2] for r in melhor]))
    if l > largura * 0.22:  # rosto enorme = câmera em tela cheia, não é sobreposição
        return None
    reg_l = min(largura, l * 3.4)
    reg_a = min(altura, reg_l * TOPO_H / W)
    x = int(np.clip(cx - reg_l / 2, 0, largura - reg_l))
    y = int(np.clip(cy - reg_a * 0.45, 0, altura - reg_a))
    return {"x": x, "y": y, "l": int(reg_l) // 2 * 2, "a": int(reg_a) // 2 * 2}


# ---------------------------------------------------------------- legenda
def _ass_tempo(s: float) -> str:
    s = max(0.0, s)
    h, m = int(s // 3600), int(s % 3600 // 60)
    return f"{h}:{m:02d}:{s % 60:05.2f}"


def _cor_ass(hexa: str) -> str:
    hexa = hexa.lstrip("#")
    r, g, b = hexa[0:2], hexa[2:4], hexa[4:6]
    return f"&H00{b}{g}{r}".upper()


def gerar_legenda(palavras: list[dict], inicio: float, fim: float, destino: Path,
                  y_centro: int, cor: str, por_bloco: int = 3, chamada: str = "", y_chamada: int = 0,
                  etiqueta: str = ""):
    """Legenda estilo Shorts: blocos de até 3 palavras, a palavra falada acende na cor do canal."""
    ps = [w for w in palavras if w["f"] > inicio and w["i"] < fim]
    linhas = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        # legenda: areia, contorno noite e sombra dura ameixa (placa de motel)
        f"Style: L,Anton,100,{M.ass(M.AREIA)},{M.ass(M.AREIA)},{M.ass(M.NOITE)},{M.ass(M.AMEIXA)},0,0,0,0,100,100,1,0,1,6,7,5,60,60,0,1",
        # chamada: texto noite numa placa rosa com sombra dura
        f"Style: C,Anton,80,{M.ass(M.NOITE)},{M.ass(M.NOITE)},{M.ass(M.ROSA)},{M.ass(M.AMEIXA)},0,0,0,0,100,100,1,0,3,18,10,5,70,70,0,1",
        # etiqueta do quadro (GTA 6 / GTA RP...): placa azul
        f"Style: T,Anton,46,{M.ass(M.NOITE)},{M.ass(M.NOITE)},{M.ass(M.AZUL)},{M.ass(M.NOITE)},0,0,0,0,100,100,2,0,3,12,0,5,70,70,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    destaque = _cor_ass(cor)
    if chamada:  # faixa de chamada nos primeiros segundos (prende quem está rolando o feed)
        t = chamada.upper().replace("{", "").replace("}", "")
        linhas.append(f"Dialogue: 1,{_ass_tempo(0)},{_ass_tempo(2.8)},C,,0,0,0,,"
                      f"{{\\pos({W // 2},{y_chamada})\\fax-0.1\\fad(0,250)}}{t}")
        if etiqueta:
            e = etiqueta.upper().replace("{", "").replace("}", "")
            linhas.append(f"Dialogue: 2,{_ass_tempo(0)},{_ass_tempo(2.8)},T,,0,0,0,,"
                          f"{{\\pos({W // 2},{y_chamada - 100})\\fax-0.1\\fad(0,250)}}{e}")
    for i in range(0, len(ps), por_bloco):
        bloco = ps[i:i + por_bloco]
        for j, w in enumerate(bloco):
            ini = w["i"] - inicio
            fim_w = (bloco[j + 1]["i"] if j + 1 < len(bloco) else w["f"] + 0.25) - inicio
            textos = []
            for k, o in enumerate(bloco):
                t = o["p"].upper().replace("{", "").replace("}", "")
                textos.append(f"{{\\c{destaque}\\fscx108\\fscy108}}{t}{{\\c{M.ass(M.AREIA)}\\fscx100\\fscy100}}" if k == j else t)
            texto = " ".join(textos)
            linhas.append(f"Dialogue: 0,{_ass_tempo(ini)},{_ass_tempo(fim_w)},L,,0,0,0,,"
                          f"{{\\pos({W // 2},{y_centro})}}{texto}")
    destino.write_text("\n".join(linhas), encoding="utf-8")


# ---------------------------------------------------------------- montagem
def _escapar(caminho: Path) -> str:
    return str(caminho).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def editar_short(bruto: Path, inicio: float, fim: float, palavras: list[dict], destino: Path,
                 marca: Path | None, cor: str, chamada: str = "", pico: float | None = None,
                 audio: Path | None = None, etiqueta: str = "", tela_inteira: bool = False) -> dict:
    """`pico`: segundo (no arquivo) da reação, ganha um zoom rápido. `audio`: arquivo com a voz isolada.
    `tela_inteira`: não separa a webcam (quadro dos gringos: o vídeo vai inteiro, com o card em cima)."""
    webcam = None if tela_inteira else achar_webcam(bruto, inicio, fim)
    topo_video = TOPO_H
    legenda = destino.with_suffix(".ass")
    largura, altura, _ = info_video(bruto)

    if webcam:
        c = webcam
        filtro = (
            f"[0:v]split=2[a][b];"
            f"[a]crop={c['l']}:{c['a']}:{c['x']}:{c['y']},scale={W}:{TOPO_H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{TOPO_H}[topo];"
            f"[b]crop=ih*{W}/{JOGO_H}:ih:(iw-ih*{W}/{JOGO_H})/2:0,scale={W}:{JOGO_H}[jogo];"
            f"[topo][jogo]vstack[v0]"
        )
        y_legenda, y_marca = TOPO_H + 230, TOPO_H + 30
        y_chamada = TOPO_H
    else:
        alt_fg = int(W * altura / largura) // 2 * 2
        filtro = (
            f"[0:v]split=2[a][b];"
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=25:3,"
            f"eq=brightness=-0.18[fundo];"
            f"[b]scale={W}:{alt_fg}[frente];"
            f"[fundo][frente]overlay=0:(H-h)/2[v0]"
        )
        y_legenda, y_marca = (H + alt_fg) // 2 + 170, (H - alt_fg) // 2 + 24
        y_chamada = max(160, (H - alt_fg) // 2 - 150)
        topo_video = (H - alt_fg) // 2

    gerar_legenda(palavras, inicio, fim, legenda, y_legenda, cor, chamada=chamada, y_chamada=y_chamada + 40,
                  etiqueta=etiqueta)
    if M.MONOGRAMA.exists():  # identidade Vice: marca d'água é o monograma CC
        marca = M.MONOGRAMA
    duracao = max(1.0, fim - inicio)
    entradas = ["-ss", f"{inicio:.2f}", "-to", f"{fim:.2f}", "-i", str(bruto)]
    proxima = 1
    if marca and Path(marca).exists():
        entradas += ["-i", str(marca)]
        filtro += (f";[1:v]scale=150:-1,format=rgba,colorchannelmixer=aa=0.85[m];"
                   f"[v0][m]overlay=W-w-28:{y_marca}[v1]")
        proxima = 2
    else:
        filtro += ";[v0]null[v1]"
    if pico is not None and 0.5 < pico - inicio < duracao - 0.5:
        a, b = pico - inicio - 0.35, pico - inicio + 1.1
        filtro += (f";[v1]fps=30,zoompan=z='if(between(in_time,{a:.2f},{b:.2f}),1.12,1)':d=1:"
                   f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps=30[v2]")
    else:
        filtro += ";[v1]null[v2]"
    barra = "0x" + M.hexa(M.AZUL).lstrip("#")
    flash = ""
    if pico is not None and 0.5 < pico - inicio < duracao - 0.5:  # flash rosa de 2 quadros no pico
        fa = pico - inicio - 0.35
        flash = f"drawbox=x=0:y=0:w=iw:h=ih:color=0x{M.hexa(M.ROSA).lstrip('#')}@0.35:t=fill:enable='between(t,{fa:.2f},{fa + 0.07:.2f})',"
    filtro += (f";[v2]ass='{_escapar(legenda)}':fontsdir='{_escapar(FONTES)}',fps=30,{flash}"
               f"drawbox=x=0:y=0:w='iw*t/{duracao:.2f}':h=12:color={barra}@1:t=fill,format=yuv420p[v]")
    mapa_audio = "0:a?"
    if audio:
        entradas += ["-ss", f"{inicio:.2f}", "-to", f"{fim:.2f}", "-i", str(audio)]
        mapa_audio = f"{proxima}:a"

    rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", filtro,
           "-map", "[v]", "-map", mapa_audio, "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "160k",
           "-ar", "48000", "-movflags", "+faststart", str(destino)])
    return {"layout": "webcam" if webcam else "fundo", "webcam": webcam, "topo_video": topo_video}


def momento_mais_alto(bruto: Path, inicio: float, fim: float) -> float:
    """Segundo (relativo ao arquivo) com o maior pico de volume — costuma ser a reação."""
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{inicio:.2f}", "-to", f"{fim:.2f}",
                        "-i", str(bruto), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                       capture_output=True, timeout=300)
    amostras = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32)
    if amostras.size < 8000:
        return inicio + (fim - inicio) / 2
    janela = 4000  # meio segundo
    n = amostras.size // janela
    rms = np.sqrt((amostras[: n * janela].reshape(n, janela) ** 2).mean(axis=1))
    return inicio + float(np.argmax(rms)) * 0.5 + 0.25


def abrir_no_pico(final: Path, pico_rel: float, duracao_teaser: float = 1.1) -> bool:
    """"Cold open": os primeiros ~1 s do Short mostram o pico (grito, batida) e só depois vem o começo.
    É o que os cortes que viralizam fazem pra pessoa não passar o vídeo. Só vale se o pico estiver longe do início."""
    _, _, dur = info_video(final)
    if pico_rel < 3.0 or pico_rel > dur - 1.0:
        return False
    a = max(0.0, pico_rel - 0.35)
    b = min(dur, a + duracao_teaser)
    saida = final.with_name(final.stem + ".cold.mp4")
    filtro = (f"[0:v]trim={a:.2f}:{b:.2f},setpts=PTS-STARTPTS,"
              f"drawbox=x=0:y=0:w=iw:h=ih:color=0x{M.hexa(M.ROSA).lstrip('#')}@0.25:t=fill:enable='lt(t,0.07)'[tv];"
              f"[0:a]atrim={a:.2f}:{b:.2f},asetpts=PTS-STARTPTS[ta];"
              f"[0:v]setpts=PTS-STARTPTS[mv];[0:a]asetpts=PTS-STARTPTS[ma];"
              f"[tv][ta][mv][ma]concat=n=2:v=1:a=1[v][a]")
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", str(final), "-filter_complex", filtro,
           "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
           "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(saida)])
    saida.replace(final)
    return True


def cortar_silencios(final: Path, palavras: list[dict], inicio: float, fim: float,
                     pausa_min: float = 0.6, folga: float = 0.15, limite_db: float = -32.0):
    """Jump cut automático: tira as pausas longas entre falas (só onde o áudio também está quieto,
    pra nunca cortar uma batida ou explosão do jogo sem fala). Devolve a função que converte um segundo
    do vídeo antigo no segundo do vídeo novo (ou None se nada foi cortado)."""
    ws = sorted((w for w in palavras if inicio <= w["i"] and w["f"] <= fim), key=lambda w: w["i"])
    if len(ws) < 4:
        return None
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(final), "-vn", "-ac", "1", "-ar", "8000",
                        "-f", "s16le", "-"], capture_output=True, timeout=300)
    amostras = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32)
    _, _, dur = info_video(final)
    cortes = []
    for a, b in zip(ws, ws[1:]):
        x, y = a["f"] - inicio + folga, b["i"] - inicio - folga
        if y - x < pausa_min - 2 * folga:
            continue
        trecho = amostras[int(x * 8000):int(y * 8000)]
        if trecho.size == 0:
            continue
        db = 20 * np.log10(np.sqrt((trecho ** 2).mean()) / 32768 + 1e-9)
        if db < limite_db:
            cortes.append((round(x, 2), round(y, 2)))
    total = sum(b - a for a, b in cortes)
    if total < 0.8:
        return None
    if total > dur * 0.3:  # nunca tira mais de 30% do vídeo
        cortes = sorted(cortes, key=lambda c: c[0] - c[1])[: max(1, len(cortes) // 2)]
        cortes.sort()
    expr = "+".join(f"between(t,{a},{b})" for a, b in cortes)
    saida = final.with_name(final.stem + ".jump.mp4")
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", str(final),
           "-vf", f"select='not({expr})',setpts=N/FRAME_RATE/TB",
           "-af", f"aselect='not({expr})',asetpts=N/SR/TB",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "160k",
           "-ar", "48000", "-movflags", "+faststart", str(saida)])
    saida.replace(final)

    def novo_tempo(t: float) -> float:
        return t - sum(min(b, t) - a for a, b in cortes if a < t)
    print(f"    jump cut: tirei {sum(b - a for a, b in cortes):.1f}s de pausa ({len(cortes)} cortes)")
    return novo_tempo
