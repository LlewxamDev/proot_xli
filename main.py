#!/usr/bin/env python3
"""
Ponto de entrada do Agente de Terminal (Termux/PRoot Ubuntu) — 100% OpenRouter.

Uso:
    export OPENROUTER_API_KEY="sua_chave_aqui"
    python3 main.py
"""
import sys


def main():
    print("Inicializando agente e buscando modelos gratuitos no OpenRouter...")
    from ui import AgentUI

    try:
        ui = AgentUI()
    except RuntimeError as e:
        print(f"\nErro: {e}\n")
        sys.exit(1)

    try:
        ui.run()
    except (KeyboardInterrupt, EOFError):
        pass

    print("\nAté logo!")


if __name__ == "__main__":
    main()
