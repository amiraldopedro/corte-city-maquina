"""Kit de thumb: para cada vídeo, um PDF com os melhores frames (de preferência com rosto e boa
expressão), as variações de título e um texto pronto para colar numa IA de imagem.
Também sai um ZIP com os frames em alta e o texto, para anexar direto na IA.
"""
from __future__ import annotations

import textwrap
import zipfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import FONTES
from .editar import frame_em, info_video


def _detector():
    xml = Path(getattr(getattr(cv2, "data", None), "haarcascades", "")) / "haarcascade_frontalface_default.xml"
    return cv2.CascadeClassifier(str(xml)) if xml.exists() else None


def melhores_frames(arquivo: Path, inicio: float, fim: float, n: int = 6, pico: float | None = None) -> list[tuple[float, np.ndarray]]:
    """Nota cada frame: rosto grande + nitidez + perto do pico da reação. Pega os n melhores, espaçados."""
    det = _detector()
    _, altura, _ = info_video(arquivo)
    passos = np.arange(inicio + 0.5, max(inicio + 1, fim - 0.3), 0.7)
    candidatos = []
    for t in passos:
        img = frame_em(arquivo, float(t))
        if img is None:
            continue
        cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        nitidez = cv2.Laplacian(cinza, cv2.CV_64F).var()
        rosto = 0.0
        if det is not None:
            rs = det.detectMultiScale(cinza, 1.1, 6, minSize=(int(altura * 0.06),) * 2)
            if len(rs):
                rosto = max(l * a for (_, _, l, a) in rs) / (img.shape[0] * img.shape[1])
        perto = 1.0 if pico is not None and abs(t - pico) < 2.5 else 0.0
        nota = rosto * 40 + min(nitidez, 800) / 800 + perto * 0.8 + (0.6 if rosto else 0)
        candidatos.append((nota, float(t), img))
    candidatos.sort(key=lambda c: -c[0])
    escolhidos = []
    for nota, t, img in candidatos:
        if all(abs(t - e[0]) >= 2.0 for e in escolhidos):
            escolhidos.append((t, img))
        if len(escolhidos) == n:
            break
    return sorted(escolhidos, key=lambda e: e[0])


def prompt_ia(titulo: str, gancho: str, nome: str, jogo: str, vertical: bool, idioma: str) -> str:
    formato = "vertical 1080x1920 (capa de Shorts)" if vertical else "horizontal 1280x720 (thumbnail de YouTube)"
    if idioma != "pt":
        formato = "vertical 1080x1920 (Shorts cover)" if vertical else "horizontal 1280x720 (YouTube thumbnail)"
        return (f"Create a YouTube thumbnail, {formato}, "
                f"using the attached frame(s) of streamer {nome} playing {jogo}. Keep the streamer's REAL face from the frame "
                f"(do not invent another person), enlarge it and push the expression (shock/laughing). Background: the {jogo} scene "
                f"from the frame, slightly blurred, high contrast and saturated. Big short text: \"{gancho}\" in a thick font, "
                f"yellow with black outline, max 3 words. Add one red arrow or circle pointing at the key element. "
                f"Video title (do not write it on the image): \"{titulo}\".")
    return (f"Crie uma thumbnail {formato} usando o(s) frame(s) anexado(s) do streamer {nome} jogando {jogo}.\n"
            f"- Use o rosto REAL do streamer que está no frame (não invente outra pessoa). Aumente o rosto e exagere a "
            f"expressão (susto, risada ou choque), ocupando cerca de 1/3 da imagem.\n"
            f"- Fundo: a cena do {jogo} do frame, levemente desfocada, com contraste e cor fortes.\n"
            f"- Texto grande e curto: \"{gancho}\" em fonte grossa, amarelo com contorno preto, no máximo 3 palavras.\n"
            f"- Uma seta ou círculo vermelho apontando o que importa na cena.\n"
            f"- Visual limpo, fácil de ler no celular. Não escreva o título inteiro na imagem.\n"
            f"Título do vídeo (só para contexto): \"{titulo}\"")


def gerar(frames: list[tuple[float, np.ndarray]], titulo: str, variantes: list[str], gancho: str, nome: str,
          jogo: str, cor: str, pasta: Path, mid: str, vertical: bool, idioma: str = "pt") -> tuple[Path, Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    f_t = ImageFont.truetype(str(FONTES / "Inter-ExtraBold.ttf"), 46)
    f_s = ImageFont.truetype(str(FONTES / "Inter-SemiBold.ttf"), 30)
    f_p = ImageFont.truetype(str(FONTES / "Inter-SemiBold.ttf"), 26)
    prompt = prompt_ia(titulo, gancho, nome, jogo, vertical, idioma)
    titulos = [titulo] + [v for v in variantes if v and v != titulo]

    pagina = Image.new("RGB", (1240, 1754), (250, 250, 250))
    d = ImageDraw.Draw(pagina)
    d.rectangle([0, 0, 1240, 16], fill=cor)
    y = 70
    d.text((70, y), "Kit da thumb", font=f_t, fill=(15, 15, 15)); y += 80
    d.text((70, y), "Títulos (o 1º é o que foi usado):", font=f_s, fill=(90, 90, 90)); y += 50
    for i, t in enumerate(titulos[:6], 1):
        for j, ln in enumerate(textwrap.wrap(f"{i}. {t}", 62)):
            d.text((90, y), ln, font=f_s, fill=(15, 15, 15)); y += 42
        y += 8
    y += 30
    d.text((70, y), "Texto pronto para a IA de imagem (copie e cole junto com um frame):", font=f_s, fill=(90, 90, 90)); y += 50
    for par in prompt.split("\n"):
        for ln in textwrap.wrap(par, 80):
            d.text((90, y), ln, font=f_p, fill=(15, 15, 15)); y += 36
    y += 30
    d.text((70, y), f"Palavra-gancho sugerida: {gancho}", font=f_s, fill=(15, 15, 15))
    paginas = [pagina]

    zip_path = pasta / f"{mid}_kit.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("texto_para_ia.txt", prompt + "\n\nTÍTULOS:\n" + "\n".join(f"- {t}" for t in titulos))
        for i, (t, img) in enumerate(frames, 1):
            rgb = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            arq = pasta / f"{mid}_frame{i}.jpg"
            rgb.save(arq, quality=95)
            z.write(arq, f"frame{i}_{t:.0f}s.jpg")
            p = Image.new("RGB", (1240, 1754), (250, 250, 250))
            dp = ImageDraw.Draw(p)
            dp.text((70, 60), f"Frame {i}  ({int(t // 60):02d}:{int(t % 60):02d})", font=f_t, fill=(15, 15, 15))
            rgb.thumbnail((1100, 1550))
            p.paste(rgb, ((1240 - rgb.width) // 2, 160))
            paginas.append(p)
    pdf = pasta / f"{mid}_kit.pdf"
    paginas[0].save(pdf, save_all=True, append_images=paginas[1:], resolution=150)
    return pdf, zip_path


def entregar_kit(pdf: Path, zip_path: Path, mid: str) -> dict:
    from .entrega import enviar_arquivo
    try:
        a = enviar_arquivo(pdf, f"{mid}_kit.pdf", "application/pdf")
        b = enviar_arquivo(zip_path, f"{mid}_kit.zip", "application/zip")
        return {"kit_url": a["url"], "kit_zip_url": b["url"]}
    except Exception as e:
        print(f"  aviso: kit da thumb não subiu ({str(e)[:120]})")
        return {}


def folhas_de_quadros(arquivo: Path, inicio: float, fim: float, pasta: Path, por_folha: int = 16) -> list[Path]:
    """Folhas 4x4 com quadros a cada ~1,5-3 s, cada um com o segundo escrito (pro Claude "ver" o vídeo)."""
    pasta.mkdir(parents=True, exist_ok=True)
    dur = max(1.0, fim - inicio)
    total = por_folha * (2 if dur > 40 else 1)
    tempos = [inicio + dur * (k + 0.5) / total for k in range(total)]
    fonte = ImageFont.truetype(str(FONTES / "Inter-ExtraBold.ttf"), 30)
    folhas = []
    for f in range(0, total, por_folha):
        folha = Image.new("RGB", (4 * 480, 4 * 270), (0, 0, 0))
        d = ImageDraw.Draw(folha)
        for k, t in enumerate(tempos[f:f + por_folha]):
            img = frame_em(arquivo, t)
            if img is None:
                continue
            q = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).resize((480, 270))
            x, y = (k % 4) * 480, (k // 4) * 270
            folha.paste(q, (x, y))
            d.rectangle([x, y, x + 110, y + 42], fill=(0, 0, 0))
            d.text((x + 8, y + 4), f"{t:.1f}s", font=fonte, fill=(255, 230, 0))
        destino = pasta / f"folha_{len(folhas) + 1}.jpg"
        folha.save(destino, quality=82)
        folhas.append(destino)
    return folhas
