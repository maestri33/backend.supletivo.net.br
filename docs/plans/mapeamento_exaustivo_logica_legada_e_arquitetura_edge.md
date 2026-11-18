# Mapeamento Arquitetural Completo: Da Lógica Legada (Django) à Arquitetura Canônica no Edge (Cloudflare)

> **Documento de Especificação Técnica, Auditoria Exaustiva e Governança de APIs**  
> **Repositório:** `https://github.com/maestri33/backend.supletivo.net.br`  
> **Data:** 17 de Novembro de 2026 (22:45 UTC-03:00)  
> **Status:** AUDITADO E PLANEJADO — BASE PARA REFATORAÇÃO NO CLOUDFLARE  

---

## 1. Auditoria Exaustiva da Lógica Existente no Backend Legado

Auditamos todos os módulos sob `api/` e `users/` para mapear exatamente o comportamento real do sistema hoje.

### 1.1 Módulo de Identidade e Autenticação (`users/auth/service.py` & `api/*/routers/auth.py`)
Atualmente, a lógica de entrada está duplicada em 4 grupos (`clients`, `collaborators`, `leadership`, `staff`), cada um montando um endpoint `/check` e um `/login`.

* **`check(cpf, phone, external_id, send_otp, preferred_channel, auto_capture)`:**
  * **Problema Grave:** Mistura 4 responsabilidades distintas:
    1. Validação de formato de telefone/CPF;
    2. Lookup no banco de dados para verificar existência;
    3. Disparo automático de código OTP por WhatsApp/Email/SMS;
    4. Provisionamento em segundo plano de usuário e lead (`auto_capture=True`).
  * **Efeito Colateral:** O frontend e o bot de WhatsApp não conseguem simplesmente "saber quem é o contato" sem disparar efeitos colaterais (envio de SMS indesejado, criação de registros vazios no banco).
* **`check_phone_whatsapp(phone)`:**
  * Normaliza telefone brasileiro (+55, DDD, 8 ou 9 dígitos com tratamento de nono dígito) via `_br_phone_variants`.
  * Consulta best-effort se o número possui conta ativa no WhatsApp.
* **`recover_phone(cpf, new_phone, birth_date, email, otp, method)`:**
  * Fluxo para titular trocar de número de WhatsApp sem perder o histórico do curso.
  * Valida segundo fator (data de nascimento na base ou OTP no e-mail cadastrado), atualiza o Profile, incrementa `token_version` e dispara notificação transacional.

---

### 1.2 Módulo de Lead e Captação (`users/roles/lead/service.py` & `api/clients/routers/lead.py`)
Responsável pela entrada de novos interessados no Supletivo EJA.

* **`pricing(ref=None)`:**
  * Retorna os valores vigentes: PIX à vista, parcelamento em até 12x no cartão, valores promocionais, preço âncora e comissão base do promotor.
  * Se `ref` for fornecido, resolve condições especiais vinculadas ao parceiro.
* **`referral_name(ref)`:**
  * Busca o nome do promotor ou polo responsável pelo código de indicação para saudar o aluno ("Você foi indicado por X").
* **`capture_lead(phone, cpf, name, ref, attribution)`:**
  * Cria `User` + `Profile` + `Address` + `Documents` com role `lead`.
  * Cria entidade `Lead` com status `PENDING`.
  * Trava a tabela de preços (`lock_pricing`), garantindo que o valor congelado não mude durante a negociação.
  * Salva dados de rastreamento (`LeadAttribution`: UTMs, GCLID, FBCLID, IP, User-Agent).
  * Notifica o promotor atribuído pelo lead novo.
* **`create_lead` & `_create_checkout_row`:**
  * Cria o registro `Checkout` com token curto de pagamento (`/lead/checkout/<token>`).
  * Enfileira task assíncrona para gerar cobrança no Asaas (PIX) ou InfinitePay (Cartão).
* **`pix_page_dict(token)`:**
  * Endpoint consumido pela página de pagamento web para renderizar QR Code, chave Copia e Cola, valor e contador de expiração.
* **`mark_paid(provider, provider_payment_id, receipt_url, amount)`:**
  * Webhook de gateway: marca o lead como `PAID`.
  * **Efeito de Transição Canônica:** Cria comissão para o promotor e provisiona o registro em `Enrollment` (Matrícula) herdando o polo de atendimento.

---

### 1.3 Módulo de Matrícula e Validação Documental (`users/roles/enrollment/`)
Fase obrigatória após o pagamento da matrícula. O aluno precisa comprovar os requisitos regulatórios do MEC/CEE.

* **`upload_rg_photo(slot, upload)` & `run_rg_validation`:**
  * Upload de fotos do documento de identificação (`front`, `back`, `full`).
  * Pipeline de IA / OCR para extrair nome, CPF, data de nascimento, filiação e órgão emissor.
* **`upload_address_proof` & `submit_address_proof_kinship`:**
  * Validação de comprovante de residência em nome próprio ou termo de parentesco.
* **`set_education`:**
  * Declaração do último ano e estado em que estudou antes de ingressar no EJA.
* **`set_selfie` & `run_selfie_validation`:**
  * Captura de biometria facial (selfie) e prova de vida contra o documento.
* **`conclude(enrollment)`:**
  * Homologação dos documentos pela secretaria/coordenador do polo.
  * Transição: cria o registro definitivo em `Student` e avança o status.

---

### 1.4 Módulo Acadêmico e Exame Final (`users/roles/student/`)
O aluno regularizado realiza as etapas acadêmicas até a certificação.

* **`set_platform_credentials`:**
  * Registro de credenciais de acesso ao ambiente preparatório (apostilas, simulados).
* **`reevaluate_exam_release`:**
  * Verifica se todos os documentos estão homologados e tempo mínimo regulamentar cumprido para liberar agendamento de prova.
* **`schedule_exam(subject, scheduled_at)`:**
  * Agendamento da prova final (presencial no polo autorizado ou monitorada).
* **`grade_exam(score, approved)`:**
  * Lançamento de nota da banca examinadora.
* **`issue_diploma` & `register_pickup`:**
  * Emissão do certificado e histórico escolar com registro no Diário Oficial / GDAE / CEE.

---

### 1.5 Módulo de Promotores e Parceiros (`users/roles/promoter/` & `candidate/`)
* **`invite_lead` & `ref_url`:**
  * Geração e rastreamento de links parametrizados de indicação (`supletivo.net.br/?ref=xxx`).
* **`list_commissions` & `set_promoter_pix`:**
  * Gestão de comissões por aluno matriculado e pagamento via PIX.

---

## 2. Diagnóstico Crítico: Por Que Eliminar a Rota `/public`?

A ideia inicial de criar um namespace `/api/v1/public/*` foi submetida a análise crítica de design e **deve ser descartada** pelos seguintes motivos técnicos:

1. **Anti-Padrão de Agrupamento por Nível de Auth:**  
   Organizar APIs por "nível de autenticação" (`/public`, `/private`, `/protected`) viola a arquitetura REST e a orientação a domínio. Endpoints devem ser organizados pela **entidade/contexto a que pertencem**, e não pela forma como são autenticados.
2. **Incoerência com o Padrão `/api/v1/<role>/<status>/<funcao>`:**  
   `public` não é uma role nem um estado de usuário. Jogar endpoints de preços, validações e tokens em `/public` criaria uma "pasta lixeira" sem dono, exatamente o problema que estamos eliminando do monólito.
3. **Fragilidade de Versionamento:**  
   Se amanhã uma rota hoje aberta exigir identificação ou token temporário, seu path HTTP precisaria mudar, quebrando integrações de frontends, bots e webhooks.

### Solução Arquitetural Elegante:
* Endpoints que atendem ao lead (mesmo anônimo) pertencem ao domínio do aluno em estado de captação:  
  **`/api/v1/student/lead/pricing`** (autorização pública por design).
* Endpoints de descoberta de número pertencem ao domínio central de identidade:  
  **`/api/v1/auth/check-number`**.

---

## 3. A Nova Arquitetura Canônica no Cloudflare (Edge Workers + D1/Hyperdrive)

Toda a lógica migrada para o Cloudflare seguirá contratos rigorosos, tipagem Pydantic v2 / TypeScript e divisão modular por domínio.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        CLOUDFLARE EDGE ROUTER                          │
└────────────────────────────────────────────────────────────────────────┘
          │                                              │
          ▼                                              ▼
┌───────────────────────────────┐       ┌────────────────────────────────┐
│   IDENTIDADE & RESOLUÇÃO      │       │     ROLES & ESTADOS DE FUNIL   │
│   (Auth / Lookup)             │       │     (/api/v1/<role>/<status>/) │
├───────────────────────────────┤       ├────────────────────────────────┤
│ • POST /api/v1/auth/check-number      │ • /api/v1/student/lead/*       │
│ • POST /api/v1/auth/login     │       │ • /api/v1/student/enrollment/* │
│ • POST /api/v1/auth/refresh   │       │ • /api/v1/student/academic/*   │
│ • POST /api/v1/auth/recover-phone     │ • /api/v1/student/exam/*       │
│                               │       │ • /api/v1/student/graduated/*  │
│                               │       │ • /api/v1/promoter/active/*    │
└───────────────────────────────┘       └────────────────────────────────┘
```

---

## 4. Especificação Detalhada da Primeira Fatia: Identidade & Lead

### 4.1 Endpoint Central: `POST /api/v1/auth/check-number`
Substitui o antigo `/auth/check` com foco estrito na identificação sem efeitos colaterais.

* **Finalidade:** Dado um número de telefone recebido do WhatsApp, identifica instantaneamente quem é o usuário, sua role canônica e seu estado no funil, ou sinaliza que é um novo contato.
* **Sem Efeitos Colaterais:** Não dispara OTP, não cria usuário e não altera banco. Apenas consulta e responde em <20ms na borda.

#### Schema de Entrada (`CheckNumberIn`):
```json
{
  "phone": "+5511999998888"
}
```

#### Schema de Saída (`CheckNumberOut`):
```json
{
  "found": true,
  "user": {
    "external_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "name": "Maria Silva",
    "masked_phone": "+55 11 •••••-8888",
    "role": "student",
    "status": "enrollment"
  },
  "is_whatsapp_valid": true
}
```
*Se `found == false`:*
```json
{
  "found": false,
  "user": null,
  "is_whatsapp_valid": true,
  "suggested_role": "student",
  "suggested_status": "lead"
}
```

---

### 4.2 Endpoints da Role `student` no Estado `lead`

Namespace: **`/api/v1/student/lead/`**

| Método | Endpoint | Autenticação | Função de Negócio |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/student/lead/pricing` | Aberta (Pública) | Retorna tabela oficial de preços e parcelamentos. Suporta query `?ref=xxx` para condições de promotor. |
| `POST` | `/api/v1/student/lead/capture` | Aberta / Token Bot | Provisiona o lead no banco com travamento de preço (`lock_pricing`) e atribuição de tráfego/promotor. |
| `POST` | `/api/v1/student/lead/checkout` | Aberta / Token Bot | Gera cobrança no gateway (PIX / Cartão) e devolve link curto e payload de pagamento. |
| `GET` | `/api/v1/student/lead/status/{token}` | Aberta | Consulta o status de pagamento do checkout em tempo real. |

---

## 5. Como o Dify v1.19.0 Opera Nessa Arquitetura

O Dify utiliza essa separação para garantir **zero alucinação**:

1. **Passo 1 (Triagem na Chegada):**  
   Ao receber a mensagem no Chatwoot / WhatsApp, o webhook chama `/api/v1/auth/check-number`.
2. **Passo 2 (Injeção de Variáveis no Dify):**  
   O Dify recebe no payload de entrada:
   ```json
   {
     "user_role": "student",
     "user_status": "lead",
     "user_name": "Maria"
   }
   ```
3. **Passo 3 (Seleção Estrita de Tools):**  
   O fluxo do Chatflow restringe o LLM a enxergar exclusivamente as tools do escopo `student/lead` (`get_pricing`, `create_checkout`). O modelo não tem acesso a rotas de envio de documentos ou notas de prova, tornando impossível qualquer confusão de contexto.

---

## 6. Governança e Versionamento

* **Arquivo de Especificação:** `docs/plans/plano_arquitetura_rotas_publicas_edge_e_registro_lead.md`
* **Auditoria de Código:** 100% dos routers em `api/` e services em `users/` mapeados.
* **Status:** Pronto para revisão e aprovação pelo Victor Maestri e Plannotator.
