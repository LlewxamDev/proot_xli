# Agente de Terminal — Termux/PRoot (100% OpenRouter)

Agente autônomo de terminal para rodar dentro do Ubuntu via PRoot, no Termux (Android).
Implementa os 5 pilares do roteiro original, mas **sem Gemini** — só OpenRouter, como combinado.

## O que mudou em relação à versão anterior (Gemini + histórico)

- **Gemini removido.** Só existe um provedor: OpenRouter. Sem fallback de 3 camadas — em vez
  disso, o fallback é *dentro* do próprio OpenRouter: entre múltiplas chaves de API (se você
  configurar mais de uma) e entre a lista de modelos 100% gratuitos, ranqueados automaticamente
  por aptidão para código/terminal (igual à ideia original do `openrouter_agent.py`, só que
  reescrita do zero em `agent_engine.py`).
- **Protocolo de ferramentas em JSON, não function-calling nativo.** Nem todo modelo gratuito do
  OpenRouter suporta bem o parâmetro `tools` da API da OpenAI. Em vez disso, o agente instrui o
  modelo a sempre responder com um JSON (`run_bash_command`, `save_memory` ou `final_answer`).
  Isso funciona com qualquer modelo de chat comum — é o mesmo truque usado em agentes ReAct — e
  foi a única mudança estrutural relevante em relação aos exemplos que você tinha.
- Os códigos que estavam nos seus arquivos de histórico eram só exemplos/pontos de partida — este
  projeto foi reescrito e modularizado do zero, mas resolve exatamente os mesmos 5 pilares que
  você descreveu no prompt mestre.

## Estrutura dos arquivos

| Arquivo             | Responsabilidade |
|----------------------|-------------------|
| `config.py`          | Todos os limites/ajustes num lugar só (tokens, segurança, timeouts) |
| `memory_manager.py`  | Janela deslizante + memória persistente em disco (`memoria.json`) + condensação de contexto (Pilar 3) |
| `executor.py`        | Execução assíncrona e cancelável de comandos bash + detecção de comandos perigosos (Pilares 1 e 4) |
| `agent_engine.py`    | Cliente OpenRouter, protocolo de ação em JSON, loop de ferramentas, trava de segurança, fallback (Pilares 4 e 5) |
| `ui.py`               | Adaptador da interface de chat `xli`: transcript nativo, markdown, spinner, ferramentas e aprovações inline |
| `main.py`             | Ponto de entrada |

## Instalação no Termux

```bash
# 1) No Termux (fora do PRoot), rode o instalador da base do sistema:
bash install.sh

# 2) Transfira este projeto para dentro do Ubuntu (ex: via zip, git ou termux-setup-storage)

# 3) Entre no Ubuntu e prepare o ambiente Python:
proot-distro login ubuntu
cd ~/termux_agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4) Configure sua chave do OpenRouter (pegue em https://openrouter.ai/keys):
export OPENROUTER_API_KEY="sua_chave_aqui"
# Ou, para rotação automática entre várias chaves gratuitas:
export OPENROUTER_API_KEYS="chave1,chave2"

# Para persistir entre sessões, adicione ao ~/.bashrc:
echo 'export OPENROUTER_API_KEY="sua_chave_aqui"' >> ~/.bashrc

# 5) Rode o agente:
python3 main.py
```

## Interface e comandos

A interface agora usa **xli**, uma biblioteca voltada especificamente para chats e agentes no terminal. Ela não toma a tela inteira: o transcript é gravado no scrollback nativo do terminal, o que funciona melhor em telas de celular.

- **`/model`** — troca manualmente para o próximo modelo gratuito
- **`/memory`** — mostra fatos e resumos guardados na memória persistente
- **`/clear-memory`** — limpa memória persistente e histórico
- **`/help`** — mostra os comandos disponíveis
- **`/quit`** — sai do agente
- **ESC** — interrompe cooperativamente o turno atual
- **Ctrl+C** — interrompe o turno
- **Ctrl+D** — sai

O xli também fornece input multilinha, histórico, markdown, cards para ferramentas e aprovações inline.

## Limitações conhecidas / próximos passos

- **Não testei este código num dispositivo real** (o ambiente onde eu trabalho não tem acesso à
  rede para instalar dependências e rodar de fato). A arquitetura e as APIs usadas são estáveis,
  mas é bem possível que apareça algum erro na primeira execução — me mande a mensagem de erro
  completa que eu ajusto direto no arquivo certo.
- A tecla **ESC** pode ter um pequeno atraso (~0,3–0,5s) para ser reconhecida sozinha — isso é uma
  característica do parser de teclado do `prompt_toolkit` (ele espera ver se é o início de uma
  combinação com Alt), não um bug do agente.
- A detecção de comandos perigosos (`executor.py`) é uma rede de segurança básica por regex, não
  uma sandbox de verdade — trate como um lembrete, não como proteção absoluta.
- O protocolo JSON depende do modelo "obedecer" ao formato pedido. Modelos gratuitos menores às
  vezes fogem do formato; quando isso acontece, o agente trata a resposta como texto final em vez
  de travar — mas se isso acontecer com frequência, troque de modelo com `F2`.
