"""
Interface de chat para terminal baseada em xli.

O xli foi escolhido para este projeto porque foi feito para agentes e chats:
transcript no scrollback nativo, composer persistente, markdown, spinner,
cards de ferramentas, aprovações inline e ESC cooperativo para interrupção.
"""
import asyncio
from typing import Any, Optional

import xli

from agent_engine import AgentEngine
from config import APP_TITLE


class AgentUI:
    """Adaptador entre o AgentEngine e a interface xli."""

    def __init__(self):
        self.engine = AgentEngine(on_status=self._on_engine_status)
        self._active_tool: Optional[Any] = None

        self.ui = xli.UI(
            title=APP_TITLE,
            status_fields=["model"],
            theme="codex",
        )
        self.ui.status.set(model=self.engine.model_name)

        self._register_handlers()

    def _register_handlers(self) -> None:
        @self.ui.on_prompt
        async def handle_prompt(prompt: str) -> None:
            await self._run_turn(prompt)

        @self.ui.on_interrupt
        async def handle_interrupt() -> None:
            self.engine.executor.cancel()
            self._active_tool = None

        @self.ui.command("model", description="trocar para o próximo modelo gratuito")
        async def change_model(ui, args) -> None:
            self.engine.cycle_model_manual()
            self.ui.status.set(model=self.engine.model_name)
            self.ui.note(f"Modelo alterado para: {self.engine.model_name}")

        @self.ui.command("memory", description="mostrar a memória persistente")
        async def show_memory(ui, args) -> None:
            self._show_memory()

        @self.ui.command("clear-memory", description="limpar memória persistente e histórico")
        async def clear_memory(ui, args) -> None:
            self.engine.memory.clear()
            self.engine.clear_history()
            self.ui.note("Memória persistente e histórico da conversa foram limpos.")

    def _on_engine_status(self, msg: str) -> None:
        # O callback pode ser chamado durante o processamento do turno.
        self.ui.note(msg)
        self.ui.status.set(model=self.engine.model_name)

    def _show_memory(self) -> None:
        facts = self.engine.memory.facts
        summaries = self.engine.memory.summaries

        parts = ["## Memória persistente"]

        if facts:
            parts.append("### Fatos salvos\n" + "\n".join(f"- {fact}" for fact in facts))
        else:
            parts.append("_Nenhum fato salvo ainda._")

        if summaries:
            parts.append("### Resumos de contexto\n" + "\n\n".join(summaries))

        self.ui.message("system", "\n\n".join(parts))

    async def _confirm(self, command: str) -> bool:
        decision = await self.ui.approve(
            title="Comando potencialmente perigoso",
            body=f"```bash\n{command}\n```",
            reason="O executor marcou este comando como potencialmente destrutivo.",
        )
        return decision in ("approved", "approved_for_session")

    async def _emit(self, event: dict) -> None:
        etype = event.get("type")

        if etype == "status":
            self.ui.note(event.get("text", ""))
            return

        if etype == "tool_call":
            command = event.get("command", "")
            self._active_tool = self.ui.tool(
                "bash",
                args={"command": command},
                status="running",
            )
            return

        if etype == "tool_result":
            output = event.get("output", "")
            if self._active_tool is not None:
                self._active_tool.update(status="done", output=output)
                self._active_tool = None
            else:
                self.ui.tool("bash", output=output, status="done")
            return

        if etype == "final":
            self.ui.status.set(model=self.engine.model_name)
            self.ui.message("assistant", event.get("text", ""))
            return

        if etype == "error":
            self.ui.message("system", f"**Erro:** {event.get('text', '')}")
            return

    async def _run_turn(self, user_text: str) -> None:
        self._active_tool = None
        self.ui.status.set(model=self.engine.model_name)

        try:
            with self.ui.working("Pensando"):
                await self.engine.process_turn(
                    user_text,
                    emit=self._emit,
                    confirm=self._confirm,
                )
        except asyncio.CancelledError:
            # O xli cancela cooperativamente o handler quando ESC é pressionado.
            self.engine.executor.cancel()
            raise
        except Exception as exc:
            self.ui.message("system", f"**Erro inesperado:** {exc}")
        finally:
            self._active_tool = None
            self.ui.status.set(model=self.engine.model_name)

    def run(self) -> None:
        self.ui.header(APP_TITLE)
        self.ui.note(
            "Digite sua mensagem. Comandos úteis: /model, /memory, /clear-memory. "
            "ESC interrompe o turno atual; /help mostra os comandos disponíveis."
        )
        self.ui.run()
