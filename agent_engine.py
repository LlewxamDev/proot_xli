"""
Motor do agente: comunicação com a API do OpenRouter (SDK compatível com OpenAI),
protocolo de ação em JSON, loop de ferramentas com trava de segurança e
fallback automático entre modelos/chaves gratuitos.

Por que protocolo JSON em vez de "function calling" nativo da OpenAI?
Nem todo modelo gratuito do OpenRouter suporta bem o parâmetro `tools` nativo.
Pedindo para o próprio modelo responder em JSON estruturado, o agente funciona
com QUALQUER modelo de chat comum — é o mesmo truque usado por agentes ReAct.
"""
import os
import re
import json
import urllib.request
from typing import Awaitable, Callable, Dict, Any, List, Optional

from openai import AsyncOpenAI

from config import (
    OPENROUTER_BASE_URL, OPENROUTER_MODELS_URL, OPENROUTER_SITE_URL, OPENROUTER_APP_NAME,
    DEFAULT_FALLBACK_MODELS, MAX_TOOL_STEPS,
)
from executor import BashExecutor, is_dangerous
from memory_manager import MemoryManager


SYSTEM_PROMPT_TEMPLATE = """Você é um agente autônomo especialista rodando dentro de um terminal \
Linux (Ubuntu via PRoot, dentro do Termux/Android). Você ajuda o usuário a investigar e administrar \
o sistema.

Em CADA resposta, responda SOMENTE com um objeto JSON válido (sem markdown, sem texto fora do JSON), \
em um dos formatos abaixo:

1) Para executar um comando shell:
{{"action": "run_bash_command", "command": "<comando>", "reason": "<por que está executando>"}}

2) Para gravar um fato permanente na memória (ex: versão do Android, status do Shizuku):
{{"action": "save_memory", "fact": "<fato curto e denso>"}}

3) Para responder ao usuário em texto (finaliza o turno):
{{"action": "final_answer", "text": "<sua resposta em markdown>"}}

Regras importantes:
- Continue executando os comandos necessários e só finalize quando tiver uma conclusão. Há um limite \
de segurança de {max_tools} passos de ferramenta por turno para impedir loops infinitos.
- Prefira poucos comandos objetivos a varreduras longas e desnecessárias.
- Se o comando for potencialmente destrutivo (rm -rf, dd, chmod -R 777, apt remove, mkfs etc.), \
o sistema vai pedir confirmação ao usuário antes de rodar — isso é esperado, não é um erro seu.
- Sempre responda com JSON válido. Nunca escreva texto solto fora do JSON.

{persistent_memory}
"""


def _extract_json_objects(text: str) -> List[Dict[str, Any]]:
    """Extrai objetos JSON válidos mesmo quando há mais de um na resposta."""
    decoder = json.JSONDecoder()
    objects: List[Dict[str, Any]] = []
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(value, dict) and "action" in value:
            objects.append(value)
        index = start + end
    return objects


def _extract_tool_calls(text: str) -> List[Dict[str, Any]]:
    """Converte o formato XML de tool calling de alguns modelos em ações internas."""
    actions: List[Dict[str, Any]] = []
    pattern = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.IGNORECASE | re.DOTALL)
    arg_pattern = re.compile(
        r"<arg_key>\s*(.*?)\s*</arg_key>\s*<arg_value>\s*(.*?)\s*</arg_value>",
        re.IGNORECASE | re.DOTALL,
    )
    for block in pattern.findall(text):
        name_match = re.match(r"([\w.-]+)", block.strip())
        if not name_match:
            continue
        action: Dict[str, Any] = {"action": name_match.group(1)}
        for key, value in arg_pattern.findall(block[name_match.end():]):
            action[key.strip()] = value.strip()
        actions.append(action)
    return actions


def _extract_actions(text: str) -> List[Dict[str, Any]]:
    """Aceita JSON, vários objetos JSON e <tool_call> sem expor o protocolo ao usuário."""
    actions = _extract_json_objects(text.strip())
    return actions or _extract_tool_calls(text)


def fetch_and_rank_free_models() -> List[str]:
    """Busca dinamicamente os modelos 100% gratuitos do OpenRouter, ordenados por aptidão p/ terminal/código."""
    try:
        req = urllib.request.Request(
            OPENROUTER_MODELS_URL, headers={"User-Agent": "Mozilla/5.0 (Termux Agent)"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models_data = data.get("data", [])
        free = []
        for m in models_data:
            mid = m.get("id", "")
            pricing = m.get("pricing", {})
            try:
                prompt_cost = float(pricing.get("prompt", 1))
            except (TypeError, ValueError):
                prompt_cost = 1.0
            if mid.endswith(":free") or prompt_cost == 0.0:
                free.append(m)
        if not free:
            return DEFAULT_FALLBACK_MODELS

        def score(m):
            mid = m.get("id", "").lower()
            ctx = m.get("context_length", 0) or 0
            s = 0
            if "coder" in mid:
                s += 1000
            elif "deepseek" in mid:
                s += 800
            elif "qwen" in mid:
                s += 700
            elif "llama-3.3" in mid or "llama-3.1" in mid:
                s += 600
            elif "gemini" in mid:
                s += 500
            elif "mistral" in mid:
                s += 400
            s += min(ctx / 1000, 200)
            return s

        free.sort(key=score, reverse=True)
        return [m["id"] for m in free] or DEFAULT_FALLBACK_MODELS
    except Exception:
        return DEFAULT_FALLBACK_MODELS


EmitFn = Callable[[Dict[str, Any]], Awaitable[None]]
ConfirmFn = Callable[[str], Awaitable[bool]]


class AgentEngine:
    def __init__(self, on_status: Optional[Callable[[str], None]] = None):
        api_keys_raw = os.environ.get("OPENROUTER_API_KEYS") or os.environ.get("OPENROUTER_API_KEY")
        if not api_keys_raw:
            raise RuntimeError(
                "Nenhuma chave OpenRouter encontrada. Configure antes de rodar:\n"
                '  export OPENROUTER_API_KEY="sua_chave"\n'
                "Ou, para rotação automática entre várias chaves gratuitas:\n"
                '  export OPENROUTER_API_KEYS="chave1,chave2"'
            )
        self.api_keys = [k.strip() for k in api_keys_raw.split(",") if k.strip()]
        self.key_idx = 0

        self.models_pool = fetch_and_rank_free_models()
        self.model_idx = 0

        self.memory = MemoryManager()
        self.executor = BashExecutor()
        self.history: List[Dict[str, Any]] = []
        self.on_status = on_status or (lambda msg: None)

        self._init_client()

    # ---------- Cliente / modelos ----------
    def _init_client(self):
        self.client = AsyncOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=self.api_keys[self.key_idx],
            default_headers={
                "HTTP-Referer": OPENROUTER_SITE_URL,
                "X-Title": OPENROUTER_APP_NAME,
            },
        )

    @property
    def model_name(self) -> str:
        return self.models_pool[self.model_idx]

    def switch_model_or_key(self):
        """Fallback automático: primeiro tenta rotacionar chave, depois troca de modelo."""
        if len(self.api_keys) > 1 and self.key_idx < len(self.api_keys) - 1:
            self.key_idx += 1
            self._init_client()
            self.on_status(f"Alternando para chave de API nº {self.key_idx + 1}/{len(self.api_keys)}")
        else:
            self.key_idx = 0
            self._init_client()
            old = self.model_name
            self.model_idx = (self.model_idx + 1) % len(self.models_pool)
            self.on_status(f"Modelo '{old}' indisponível → tentando '{self.model_name}'")

    def cycle_model_manual(self):
        """Atalho F2: troca manual de modelo pelo usuário."""
        self.model_idx = (self.model_idx + 1) % len(self.models_pool)
        self.on_status(f"Modelo trocado manualmente para '{self.model_name}'")

    def clear_history(self):
        self.history = []

    # ---------- Chamada de API com fallback em cascata ----------
    async def _call_model(self, messages: List[Dict[str, str]]) -> str:
        max_attempts = len(self.api_keys) * len(self.models_pool)
        attempts = 0
        while attempts < max_attempts:
            try:
                resp = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=0.4,
                )
                return resp.choices[0].message.content or ""
            except Exception as e:
                err = str(e).lower()
                if any(k in err for k in ("429", "quota", "rate", "404", "not_found", "unavailable", "500", "502", "503")):
                    self.switch_model_or_key()
                    attempts += 1
                    continue
                raise
        raise RuntimeError("Todas as chaves/modelos gratuitos esgotaram a cota. Aguarde um pouco e tente de novo.")

    async def _summarize_for_condensation(self, messages: List[Dict[str, Any]]) -> str:
        text_block = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in messages)
        prompt = [
            {"role": "system", "content": "Resuma o histórico abaixo em UM parágrafo denso (máx. 4 linhas), "
                                            "preservando fatos técnicos e decisões relevantes. Responda só "
                                            "com o parágrafo, sem JSON."},
            {"role": "user", "content": text_block[:6000]},
        ]
        try:
            return await self._call_model(prompt)
        except Exception:
            return ""

    def build_system_prompt(self) -> str:
        return SYSTEM_PROMPT_TEMPLATE.format(
            max_tools=MAX_TOOL_STEPS,
            persistent_memory=self.memory.persistent_context_block(),
        )

    # ---------- Loop principal de um turno ----------
    async def process_turn(self, user_text: str, emit: EmitFn, confirm: ConfirmFn) -> None:
        """
        Conduz um turno completo da conversa, podendo envolver várias chamadas de
        ferramenta em sequência, até o modelo dar um `final_answer`.

        `emit(evento)`  -> a UI usa para atualizar a tela (não bloqueia nada).
        `confirm(cmd)`  -> a UI usa para pedir aprovação de comandos perigosos;
                           deve devolver True/False (pode aguardar input do usuário
                           sem travar o resto do app, pois tudo roda no mesmo loop).

        Cancelar a task que envolve esta corrotina (ESC na UI) interrompe o turno
        em qualquer ponto — seja uma chamada de API, seja um comando bash rodando.
        """
        self.history.append({"role": "user", "content": user_text})
        self.history = await self.memory.trim_history(self.history, self._summarize_for_condensation)

        tool_steps = 0
        invalid_responses = 0

        while True:
            messages = [{"role": "system", "content": self.build_system_prompt()}] + self.history

            try:
                raw = await self._call_model(messages)
            except Exception as e:
                await emit({"type": "error", "text": f"Erro de API: {e}"})
                return

            actions = _extract_actions(raw)
            if not actions:
                # Não contamina o histórico nem mostra XML/JSON interno ao usuário.
                invalid_responses += 1
                if invalid_responses >= 2:
                    await emit({"type": "error", "text": "O modelo não retornou uma ação válida após duas tentativas."})
                    return
                self.history.append({"role": "user", "content": "[sistema] Resposta inválida. Retorne somente uma ação JSON válida ou blocos <tool_call> válidos."})
                await emit({"type": "status", "text": "Resposta fora do protocolo; solicitando correção ao modelo."})
                continue

            invalid_responses = 0
            # Registra apenas a forma normalizada, nunca o XML bruto do modelo.
            self.history.append({"role": "assistant", "content": json.dumps(actions, ensure_ascii=False)})

            for action in actions:
                kind = action.get("action")

                if kind == "final_answer":
                    await emit({"type": "final", "text": action.get("text", "")})
                    return

                if kind == "save_memory":
                    fact = str(action.get("fact", "")).strip()
                    if fact:
                        self.memory.add_fact(fact)
                        self.history.append({"role": "user", "content": f"[sistema] Fato salvo na memória: {fact}"})
                        await emit({"type": "status", "text": f"Memória atualizada: {fact}"})
                    continue

                if kind == "run_bash_command":
                    command = str(action.get("command", "")).strip()
                    if not command:
                        result_text = "Erro: comando vazio."
                        self.history.append({"role": "user", "content": f"[resultado do comando]\n{result_text}"})
                        await emit({"type": "tool_result", "output": result_text})
                        continue

                    tool_steps += 1
                    if tool_steps > MAX_TOOL_STEPS:
                        message = f"Interrompi por segurança após {MAX_TOOL_STEPS} passos de ferramenta."
                        self.history.append({"role": "user", "content": f"[sistema] {message}"})
                        await emit({"type": "final", "text": message})
                        return

                    if is_dangerous(command):
                        approved = await confirm(command)
                        if not approved:
                            result_text = "Usuário NÃO autorizou este comando. Ação cancelada."
                            self.history.append({"role": "user", "content": f"[resultado do comando]\n{result_text}"})
                            await emit({"type": "tool_result", "output": result_text})
                            continue

                    await emit({"type": "tool_call", "command": command})
                    result = await self.executor.run(command)
                    output = result.output
                    self.history.append({"role": "user", "content": f"[resultado do comando]\n{output}"})
                    await emit({"type": "tool_result", "output": output})
                    continue

                # Ação desconhecida: pede correção ao modelo sem vazar o protocolo para a UI.
                self.history.append({"role": "user", "content": f"[sistema] Ação desconhecida: {kind}. Use run_bash_command, save_memory ou final_answer."})
                await emit({"type": "status", "text": f"Ação desconhecida ({kind}); solicitando correção ao modelo."})
