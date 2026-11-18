#!/usr/bin/env python3
"""
Chatwoot <-> Dify Integration Bridge (Hardened)
==============================================
Conecta o Chatwoot (inboxes WhatsApp/Omnichannel) ao Dify (Workflows/Chatflows).

Funcionalidades:
- Recebe webhooks do Chatwoot (AgentBot e Account Webhook).
- Deduplica eventos por message_id para evitar respostas duplicadas.
- Filtra apenas mensagens 'incoming' de clientes (ignora mensagens de agentes ou privadas).
- Encaminha o texto para a API do Dify (/v1/chat-messages) mantendo o conversation_id persistido em SQLite.
- Posta a resposta do Dify de volta no Chatwoot com o token do AgentBot (Dify OmniRoute Bot).
- Suporta Transbordo Humano Inteligente:
  * Detecta tag [TRANSFERIR] na resposta do Dify ou gatilhos manuais configuráveis.
  * Remove a tag antes de enviar ao cliente.
  * Cria uma nota interna privada no Chatwoot alertando a equipe humana.
  * Altera o status da conversa para 'open' (fila humana) e adiciona label 'transbordo-humano'.
  * Pausa o bot para aquela conversa até que seja resolvida ou reativada (/bot on).
"""

import os
import re
import json
import sqlite3
import logging
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import requests

# Configurações do Ambiente
CHATWOOT_URL = os.getenv("CHATWOOT_URL", "http://127.0.0.1:3000").rstrip("/")
CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_TOKEN", "LZD3QhFz1kh1fvjTjE6j6NHU")
CHATWOOT_BOT_TOKEN = os.getenv("CHATWOOT_BOT_TOKEN", "FEUYKPGwrhV8F1FiA4JTpbYq")
CHATWOOT_ACCOUNT_ID = int(os.getenv("CHATWOOT_ACCOUNT_ID", "1"))

DIFY_URL = os.getenv("DIFY_URL", "http://127.0.0.1:8090").rstrip("/")
DIFY_API_KEY = os.getenv("DIFY_API_KEY", "app-lm2qFiq1DrpTBW1TlbKNbZu5")

PORT = int(os.getenv("BRIDGE_PORT", "8000"))
DB_PATH = os.getenv("DB_PATH", "bridge_sessions.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("ChatwootDifyBridge")

# Cache em memória para deduplicação de mensagens (últimos 1000 IDs)
PROCESSED_MESSAGES = deque(maxlen=1000)
PROCESSED_SET = set()

def is_duplicate(message_id):
    if not message_id:
        return False
    if message_id in PROCESSED_SET:
        return True
    if len(PROCESSED_MESSAGES) >= 1000:
        oldest = PROCESSED_MESSAGES.popleft()
        PROCESSED_SET.discard(oldest)
    PROCESSED_MESSAGES.append(message_id)
    PROCESSED_SET.add(message_id)
    return False

# Inicialização do Banco SQLite para mapeamento de sessões
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversation_map (
            chatwoot_conv_id INTEGER PRIMARY KEY,
            dify_conv_id TEXT,
            paused INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_dify_session(chatwoot_conv_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT dify_conv_id, paused FROM conversation_map WHERE chatwoot_conv_id = ?", (chatwoot_conv_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"dify_conv_id": row[0], "paused": bool(row[1])}
    return {"dify_conv_id": None, "paused": False}

def save_dify_session(chatwoot_conv_id: int, dify_conv_id: str, paused: bool = False):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO conversation_map (chatwoot_conv_id, dify_conv_id, paused, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(chatwoot_conv_id) DO UPDATE SET
            dify_conv_id = excluded.dify_conv_id,
            paused = excluded.paused,
            updated_at = CURRENT_TIMESTAMP
    """, (chatwoot_conv_id, dify_conv_id, 1 if paused else 0))
    conn.commit()
    conn.close()

def set_conversation_paused(chatwoot_conv_id: int, paused: bool):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE conversation_map SET paused = ?, updated_at = CURRENT_TIMESTAMP WHERE chatwoot_conv_id = ?", (1 if paused else 0, chatwoot_conv_id))
    conn.commit()
    conn.close()

# Integração Dify
def call_dify(query: str, dify_conv_id: str = None, user_id: str = "chatwoot-user"):
    payload = {
        "inputs": {},
        "query": query,
        "response_mode": "blocking",
        "user": str(user_id)
    }
    if dify_conv_id:
        payload["conversation_id"] = dify_conv_id

    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(f"{DIFY_URL}/v1/chat-messages", headers=headers, json=payload, timeout=55)
        if response.status_code == 200:
            data = response.json()
            return {
                "answer": data.get("answer", ""),
                "conversation_id": data.get("conversation_id"),
                "task_id": data.get("task_id")
            }
        else:
            logger.error(f"Erro Dify API {response.status_code}: {response.text}")
            return None
    except Exception as e:
        logger.error(f"Exceção ao chamar Dify API: {e}")
        return None

# Ações no Chatwoot
def send_chatwoot_message(conversation_id: int, content: str, private: bool = False):
    # Se for mensagem pública do bot, usamos o token do bot para ficar atribuído à IA
    token = CHATWOOT_API_TOKEN if private else CHATWOOT_BOT_TOKEN
    headers = {
        "api_access_token": token,
        "Content-Type": "application/json"
    }
    payload = {
        "content": content,
        "message_type": "outgoing",
        "private": private
    }
    try:
        url = f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/messages"
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        return resp.status_code in (200, 201)
    except Exception as e:
        logger.error(f"Exceção ao enviar mensagem ao Chatwoot: {e}")
        return False

def trigger_human_handoff(conversation_id: int, reason: str = "Solicitação do cliente"):
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN,
        "Content-Type": "application/json"
    }
    # 1. Nota interna avisando a equipe humana
    note_content = (
        f"🚨 **[TRANSBORDO IA ➔ HUMANO]**\n"
        f"Motivo: {reason}\n"
        f"O bot de IA foi pausado nesta conversa para permitir o atendimento humano imediato."
    )
    send_chatwoot_message(conversation_id, note_content, private=True)

    # 2. Altera status da conversa para 'open'
    try:
        url_status = f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/toggle_status"
        requests.post(url_status, headers=headers, json={"status": "open"}, timeout=10)
    except Exception as e:
        logger.error(f"Erro ao alterar status da conversa {conversation_id}: {e}")

    # 3. Adiciona label de transbordo
    try:
        url_labels = f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/labels"
        requests.post(url_labels, headers=headers, json={"labels": ["transbordo-humano", "atendimento-ia"]}, timeout=10)
    except Exception as e:
        logger.error(f"Erro ao adicionar label na conversa {conversation_id}: {e}")

    # 4. Marca conversa como pausada para a IA
    set_conversation_paused(conversation_id, paused=True)
    logger.info(f"Transbordo humano concluído com sucesso para conversa #{conversation_id}")

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/healthz", "/"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "healthy",
                "service": "Chatwoot-Dify-Bridge",
                "chatwoot_url": CHATWOOT_URL,
                "dify_url": DIFY_URL
            }).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            payload = json.loads(post_data.decode("utf-8"))
        except Exception as e:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid JSON")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"received"}')

        self.process_chatwoot_event(payload)

    def process_chatwoot_event(self, payload: dict):
        event = payload.get("event")
        if event not in ("message_created", None):
            return

        message_type = payload.get("message_type")
        if message_type not in ("incoming", 0):
            return

        if payload.get("private", False):
            return

        message_id = payload.get("id")
        if is_duplicate(message_id):
            logger.info(f"Mensagem #{message_id} já processada. Ignorando duplicata.")
            return

        content = payload.get("content", "").strip()
        if not content:
            return

        conversation = payload.get("conversation", {})
        conversation_id = conversation.get("id") or payload.get("conversation_id")
        if not conversation_id:
            logger.warning("Evento sem conversation_id descartado.")
            return

        sender = payload.get("sender", {})
        sender_id = sender.get("id") or "anonymous"
        sender_phone = sender.get("phone_number") or sender_id

        # Comandos de controle manual para atendentes humanos no chat
        if content == "/bot on":
            set_conversation_paused(conversation_id, paused=False)
            send_chatwoot_message(conversation_id, "🤖 [IA Reativada] O bot voltará a responder automaticamente.", private=True)
            return
        elif content == "/bot off":
            set_conversation_paused(conversation_id, paused=True)
            send_chatwoot_message(conversation_id, "⏸️ [IA Pausada] O bot foi desativado temporariamente para este chat.", private=True)
            return

        session = get_dify_session(conversation_id)
        if session.get("paused"):
            logger.info(f"Conversa #{conversation_id} em atendimento humano. Bot ignorando mensagem.")
            return

        dify_conv_id = session.get("dify_conv_id")
        logger.info(f"Processando mensagem cliente na conversa #{conversation_id}: '{content[:60]}...'")

        dify_result = call_dify(
            query=content,
            dify_conv_id=dify_conv_id,
            user_id=f"wa-{sender_phone}"
        )

        if not dify_result:
            logger.error("Falha ao obter resposta do Dify.")
            return

        raw_answer = dify_result.get("answer", "").strip()
        new_dify_conv_id = dify_result.get("conversation_id")

        save_dify_session(conversation_id, new_dify_conv_id, paused=False)

        handoff_requested = "[TRANSFERIR]" in raw_answer
        clean_answer = raw_answer.replace("[TRANSFERIR]", "").strip()

        if clean_answer:
            send_chatwoot_message(conversation_id, clean_answer, private=False)

        if handoff_requested:
            trigger_human_handoff(conversation_id, reason="IA identificou solicitação de suporte humano")

def run():
    init_db()
    server_address = ("0.0.0.0", PORT)
    httpd = ThreadedHTTPServer(server_address, WebhookHandler)
    logger.info(f"Chatwoot <-> Dify Bridge ouvindo na porta {PORT}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Encerrando servidor...")
        httpd.server_close()

if __name__ == "__main__":
    run()
