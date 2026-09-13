"""
Configurações centrais do Agente de Terminal (Termux / PRoot Ubuntu).
Ajuste aqui os limites de segurança, memória e tokens sem mexer no resto do código.
"""
import os
from pathlib import Path

# --- Diretórios e arquivos ---
BASE_DIR = Path(__file__).resolve().parent
MEMORY_FILE = BASE_DIR / "memoria.json"

# --- OpenRouter ---
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS_URL = f"{OPENROUTER_BASE_URL}/models"
OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "https://github.com/termux-agent")
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "Termux Terminal Agent")

# Usado se a busca dinâmica de modelos gratuitos falhar (sem internet, API fora do ar etc.)
DEFAULT_FALLBACK_MODELS = [
    "qwen/qwen-2.5-coder-32b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-r1:free",
    "google/gemini-2.0-flash-exp:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
]

# --- Janela de contexto / economia de tokens (Pilar 3) ---
MAX_HISTORY_MESSAGES = 12        # nº de mensagens "cruas" mantidas na janela deslizante
CONDENSE_CHUNK = 10               # quantas mensagens antigas condensar de uma vez em resumo
MAX_BASH_OUTPUT_CHARS = 1500      # truncamento de stdout/stderr de comandos

# --- Segurança / Loop Guardrail (Pilar 4) ---
MAX_CONSECUTIVE_TOOL_CALLS = 3    # comandos bash seguidos antes de exigir relatório em texto
BASH_TIMEOUT_SECONDS = 60

# Padrões de comando considerados perigosos — exigem confirmação explícita do usuário
DANGEROUS_PATTERNS = [
    r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\b",   # rm -rf, -fr, -Rf, --recursive --force (parcial)
    r"\bmkfs(\.\w+)?\b",
    r"\bdd\s+if=",
    r"\bchmod\s+-R\s+777\b",
    r"\bapt(-get)?\s+(remove|purge)\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r">\s*/dev/sd\w+",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",   # fork bomb clássica
]

# --- UI ---
APP_TITLE = "Agente de Terminal — Termux/PRoot (OpenRouter)"
