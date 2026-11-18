"""Temporário: transcreve e separa voz/jogo dos áudios do Davy."""
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, ".")
import numpy as np, torch
from maquina.transcrever import transcrever
from maquina import voz
voz._garantir()
from demucs.apply import apply_model
m = voz._modelo(); SR = voz.SR
for nome in ("curto", "longo"):
    f = Path(f"tmp_davy/{nome}.flac")
    json.dump(transcrever(f, "pt", "small"), open(f"tmp_davy/{nome}.palavras.json", "w"), ensure_ascii=False)
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(f), "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True)
    a = np.frombuffer(r.stdout, dtype=np.float32).reshape(-1, 2).T.copy(); w = torch.from_numpy(a)
    ref = w.mean(0); mu, sd = ref.mean(), ref.std() + 1e-8
    with torch.no_grad():
        fo = apply_model(m, ((w - mu) / sd)[None], device="cpu", split=True, overlap=0.1, progress=False)[0] * sd + mu
    jogo = sum(fo[i] for i, s in enumerate(m.sources) if s != "vocals")
    for rot, x in (("jogo", jogo), ("voz", fo[m.sources.index("vocals")])):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "pipe:0",
                        "-c:a", "flac", f"tmp_davy/{nome}.{rot}.flac"], input=x.T.contiguous().numpy().astype(np.float32).tobytes(), check=True)
    print("ok", nome)
