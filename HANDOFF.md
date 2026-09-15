# 📋 Backend Principal (`services/backend`) — Handoff Técnico

> **Última Atualização:** 26 de Agosto de 2026  
> **Status:** Em Validação com o Usuário (Aguardando homologação de envios e testes)

---

## 🎯 1. Escopo das Alterações Recentes

### 1.1. Síntese de Voz (TTS) 100% no Backend via OmniRoute (`http://10.0.1.35`)
- **Módulo `integrations.ai.tts` Criado e Validado:**
  - Roteamento exclusivo via endpoint OpenAI-compatible do OmniRoute em `POST http://10.0.1.35/v1/audio/speech`.
  - **Regra Cruzada de Gênero (Victor Rule):**
    * Destinatário Homem (`gender == "M"`) ➔ Recebe **Voz Feminina** (`Portuguese_SereneWoman` / `nova`).
    * Destinatária Mulher (`gender == "F"`) ➔ Recebe **Voz Masculina** (`Portuguese_GentleTeacher` / `onyx`).
    * Destinatário Desconhecido (`gender == None`) ➔ Recebe **Voz Feminina Padrão**.
  - **Cadeia de Fallback Resiliente (`TTS_CHAIN`):**
    * 1. `minimax/speech-01-hd` (`Portuguese_SereneWoman` / `Portuguese_GentleTeacher`)
    * 2. `openai/tts-1` (`nova` / `onyx`)
    * 3. `deepgram/aura-2-thalia-en` (`aura-2-thalia-en` / `aura-2-apollo-en`)
  - **Storage e Cache:**
    * Áudio sintetizado gravado em `/media/ai/tts/<hash>.ogg` com deduplicação SHA-256 e URL pública (`EXTERNAL_URL`).
    * Fallback sintético local em modo offline para evitar travamento da fila.

### 1.2. Remoção Definitiva de Storytelling
- **Modelo `notify.Template`:**
  - Removidas colunas `storytelling` e `story_prompt`.
  - Migration aplicada no PostgreSQL: `0008_remove_storytelling.py`.
- **Limpeza no Pipeline:**
  - Removidas chamadas de IA durante o envio em `notify.interface.events.send_event`.
  - Removidos argumentos de storytelling em schemas e seeds.

### 1.3. Endpoints Staff Adicionados (`api.staff.routers.notify`)
- `POST /api/v1/staff/notify/templates/ai-assist`:
  - Assistente de redação de templates com IA via OmniRoute (`auto/best-fast`).
- `GET /api/v1/staff/notify/tts/config`:
  - Retorna URL do OmniRoute, lista da cadeia de TTS ativa e descrição da regra cruzada.
- `POST /api/v1/staff/notify/tts/probe`:
  - Teste de áudio em tempo real com diagnóstico por modelo e retorno da URL pública do áudio.

---

## 🛠️ 2. Arquivos Modificados / Criados

- `services/backend/integrations/ai/tts.py`: Módulo de síntese TTS, cadeia de fallback e regra de gênero cruzado.
- `services/backend/notify/models.py`: Modelo `Template` sem storytelling.
- `services/backend/notify/migrations/0008_remove_storytelling.py`: Migration do banco de dados.
- `services/backend/notify/interface/events.py`: Lógica de injeção de TTS antes do despacho para o notify.
- `services/backend/api/staff/routers/notify.py`: Endpoints de IA, histórico, templates e TTS probe/config.
- `services/backend/api/staff/schemas.py`: Schemas Pydantic v2 para `AiAssistIn`, `TtsConfigOut`, `TtsProbeIn`, `TtsProbeOut`.

---

## 🧪 3. Validação Executada

- `GET /api/v1/staff/notify/tts/config`: Retornou HTTP 200 com a cadeia de 3 modelos.
- `POST /api/v1/staff/notify/tts/probe`: Retornou HTTP 200 com diagnóstico completo do OmniRoute e geração de áudio.
- Disparos reais de teste via `send_event` executados para `5543996648750` e `victormaestri@gmail.com`.
