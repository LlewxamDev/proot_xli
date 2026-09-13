#!/data/data/com.termux/files/usr/bin/bash
# Instala a base Termux + PRoot Ubuntu.
# Rode este script no Termux, fora do PRoot.
set -e

echo "Atualizando Termux e instalando proot-distro..."
pkg update -y
pkg upgrade -y
pkg install -y proot-distro

if ! proot-distro list -q | grep -qx "ubuntu"; then
    echo "Instalando Ubuntu via proot-distro..."
    proot-distro install ubuntu
fi

echo "Configurando dependências dentro do Ubuntu..."
proot-distro login ubuntu -- bash -c '
    apt update
    apt install -y python3 python3-pip python3-venv nano git curl
'

echo ""
echo "Base pronta. Copie o projeto para dentro do Ubuntu e rode:"
echo "  proot-distro login ubuntu"
echo "  cd ~/termux_agent"
echo "  python3 -m venv venv"
echo "  source venv/bin/activate"
echo "  pip install -r requirements.txt"
echo '  export OPENROUTER_API_KEY="sua_chave_aqui"'
echo "  python3 main.py"
