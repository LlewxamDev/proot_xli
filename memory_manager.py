"""
Gerenciamento de memória (Pilar 3 do roteiro):
- Janela deslizante: mantém só as últimas N mensagens "cruas" na conversa.
- Memória persistente em disco (memoria.json): fatos que a própria IA grava
  autonomamente via a ação `save_memory` (ex: "Shizuku porta 18877 inativa").
- Condensação automática: antes de descartar mensagens antigas da janela,
  gera um resumo denso via uma chamada leve à própria API, em vez de
  simplesmente jogar fora o contexto.
"""
import json
import time
from pathlib import Path
from typing import Awaitable, Callable, List, Dict, Any

from config import MEMORY_FILE, MAX_HISTORY_MESSAGES, CONDENSE_CHUNK


class MemoryManager:
    def __init__(self, memory_file: Path = MEMORY_FILE):
        self.memory_file = memory_file
        self.facts: List[str] = []
        self.summaries: List[str] = []
        self._load()

    # ---------- Persistência em disco ----------
    def _load(self) -> None:
        if self.memory_file.exists():
            try:
                data = json.loads(self.memory_file.read_text(encoding="utf-8"))
                self.facts = data.get("facts", [])
                self.summaries = data.get("summaries", [])
            except Exception:
                self.facts, self.summaries = [], []

    def _save(self) -> None:
        data = {"facts": self.facts, "summaries": self.summaries, "updated_at": time.time()}
        self.memory_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_fact(self, fact: str) -> None:
        """Chamado quando a IA usa a ação save_memory para gravar uma descoberta permanente."""
        fact = fact.strip()
        if fact and fact not in self.facts:
            self.facts.append(fact)
            self._save()

    def clear(self) -> None:
        self.facts, self.summaries = [], []
        self._save()

    # ---------- Bloco injetado no prompt de sistema ----------
    def persistent_context_block(self) -> str:
        if not self.facts and not self.summaries:
            return ""
        parts = []
        if self.facts:
            parts.append("Fatos conhecidos sobre este sistema/usuário (memória persistente):\n- " + "\n- ".join(self.facts))
        if self.summaries:
            parts.append("Resumo de trechos anteriores da conversa (já descartados da janela):\n" + "\n".join(self.summaries))
        return "\n\n".join(parts)

    # ---------- Janela deslizante + condensação automática ----------
    async def trim_history(
        self,
        history: List[Dict[str, Any]],
        summarize_fn: Callable[[List[Dict[str, Any]]], Awaitable[str]],
    ) -> List[Dict[str, Any]]:
        """
        Mantém só as últimas MAX_HISTORY_MESSAGES mensagens na conversa "crua".
        Antes de descartar o excesso, condensa esse bloco em um parágrafo
        (via `summarize_fn`, uma chamada leve à própria API) e guarda o
        resultado em self.summaries, para não perder o contexto de vez.
        """
        if len(history) <= MAX_HISTORY_MESSAGES:
            return history

        overflow = len(history) - MAX_HISTORY_MESSAGES
        cut = max(overflow, CONDENSE_CHUNK)
        to_condense = history[:cut]
        remainder = history[cut:]

        try:
            summary = await summarize_fn(to_condense)
            if summary:
                self.summaries.append(summary.strip())
                self.summaries = self.summaries[-5:]  # não deixa crescer para sempre
                self._save()
        except Exception:
            pass  # se a condensação falhar, apenas descarta (comportamento antigo, sem quebrar o app)

        return remainder
