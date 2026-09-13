"""
Execução assíncrona e não-bloqueante de comandos shell (Pilares 1 e 4 do roteiro).

Usa asyncio.create_subprocess_shell em vez de subprocess.run: o comando roda
em segundo plano dentro do mesmo event loop da interface, então a digitação
do usuário nunca trava. O cancelamento (tecla ESC na UI) mata o processo
filho diretamente.
"""
import asyncio
import re
from dataclasses import dataclass
from typing import Optional

from config import MAX_BASH_OUTPUT_CHARS, BASH_TIMEOUT_SECONDS, DANGEROUS_PATTERNS

_DANGEROUS_RE = re.compile("|".join(DANGEROUS_PATTERNS), re.IGNORECASE)


@dataclass
class ExecResult:
    output: str
    cancelled: bool = False
    timed_out: bool = False


def is_dangerous(command: str) -> bool:
    """Checagem simples por regex — não é infalível, é uma rede de segurança básica."""
    return bool(_DANGEROUS_RE.search(command))


def _truncate(output: str) -> str:
    """Preserva a metade inicial e final da saída, cortando o meio (economia de tokens)."""
    if len(output) <= MAX_BASH_OUTPUT_CHARS:
        return output
    half = MAX_BASH_OUTPUT_CHARS // 2
    marker = f"\n\n[... saída truncada de {len(output)} para {MAX_BASH_OUTPUT_CHARS} chars ...]\n\n"
    return output[:half] + marker + output[-half:]


class BashExecutor:
    """Executa comandos em segundo plano, permitindo cancelamento a qualquer momento pela UI."""

    def __init__(self):
        self._current_proc: Optional[asyncio.subprocess.Process] = None

    async def run(self, command: str) -> ExecResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._current_proc = proc
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=BASH_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ExecResult(output="Erro: o comando excedeu o tempo limite.", timed_out=True)

            out = ""
            if stdout:
                out += f"STDOUT:\n{stdout.decode(errors='replace').strip()}"
            if stderr:
                if out:
                    out += "\n"
                out += f"STDERR:\n{stderr.decode(errors='replace').strip()}"
            if not out:
                out = "Comando executado com sucesso (sem saída)."
            return ExecResult(output=_truncate(out))

        except asyncio.CancelledError:
            # A tarefa (task) que envolve este run() foi cancelada pela UI (ESC).
            if self._current_proc and self._current_proc.returncode is None:
                self._current_proc.kill()
            raise  # deixa a task subir como cancelada — o chamador trata isso
        except Exception as e:
            return ExecResult(output=f"Erro ao executar comando: {e}")
        finally:
            self._current_proc = None

    def cancel(self) -> bool:
        """Mata imediatamente o processo em execução, se houver (chamado pela UI ao pressionar ESC)."""
        if self._current_proc and self._current_proc.returncode is None:
            self._current_proc.kill()
            return True
        return False
