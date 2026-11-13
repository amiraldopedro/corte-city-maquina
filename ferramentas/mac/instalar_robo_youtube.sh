#!/bin/bash
# Instalador do Robô do YouTube da Corte City (roda uma vez no Mac).
# Uso: abra o Terminal e rode:  bash ~/Downloads/instalar_robo_youtube.sh
set -e
PASTA="$HOME/.corte-city"
AQUI="$(cd "$(dirname "$0")" && pwd)"
echo ""
echo "=== Robô do YouTube - Corte City ==="
echo ""

# 1) Homebrew + yt-dlp + ffmpeg
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v brew >/dev/null 2>&1; then
  echo "Instalando o Homebrew (o Mac vai pedir a sua senha do computador)..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
fi
echo "Instalando yt-dlp e ffmpeg..."
brew install yt-dlp ffmpeg >/dev/null || brew upgrade yt-dlp ffmpeg >/dev/null || true

# 2) Chave do GitHub (fica guardada nas Chaves do macOS, não em arquivo)
if ! security find-generic-password -s corte-city-github -w >/dev/null 2>&1; then
  echo ""
  echo "Cole a mesma chave do GitHub que você usa no painel (ela não aparece enquanto você cola) e aperte Enter:"
  read -rs CHAVE
  echo ""
  security add-generic-password -a "$USER" -s corte-city-github -w "$CHAVE" -U
  unset CHAVE
  echo "Chave guardada nas Chaves do macOS."
fi

# 3) Copia o robô e agenda para rodar a cada 15 minutos (enquanto o Mac estiver ligado)
mkdir -p "$PASTA"
cp "$AQUI/robo_youtube.py" "$PASTA/robo_youtube.py"
PLIST="$HOME/Library/LaunchAgents/com.cortecity.robo-youtube.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.cortecity.robo-youtube</string>
  <key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>$PASTA/robo_youtube.py</string></array>
  <key>StartInterval</key><integer>900</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$PASTA/saida.log</string>
  <key>StandardErrorPath</key><string>$PASTA/saida.log</string>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "Pronto! O robô roda a cada 15 minutos enquanto o Mac estiver ligado."
echo "Pra ver o que ele fez:  cat ~/.corte-city/robo_youtube.log"
echo "Pra desligar:           launchctl unload ~/Library/LaunchAgents/com.cortecity.robo-youtube.plist"
echo ""
