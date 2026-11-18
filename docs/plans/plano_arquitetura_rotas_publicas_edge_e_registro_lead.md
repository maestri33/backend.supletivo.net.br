# Plano Arquitetural: Rotas Públicas na Borda (Cloudflare), Auditoria de Registro de Lead e Ciclo de Vida EJA

> **Documento de Especificação Técnica e Governança**  
> **Repositório:** `https://github.com/maestri33/backend.supletivo.net.br`  
> **Autores:** Dify Specialist, Arquiteto de Identidade, Arquiteto de APIs, Victor Maestri  
> **Data:** 17 de Novembro de 2026 (22:15 UTC-03:00)  
> **Status:** PLANEJADO & AUDITADO — PRONTO PARA IMPLEMENTAÇÃO  

---

## 1. Alinhamento de Realidade de Negócio (EJA Supletivo)

### 1.1 O que o Sistema É e o que NÃO É
* **NÃO É um LMS tradicional de aulas semanais:** O Supletivo EJA não faz liberação gradativa de disciplinas ou vídeo-aulas semanais com frequência presencial de escola regular.
* **O QUE É:** É uma plataforma de aceleração, certificação e homologação educacional conforme diretrizes da LDB e Conselhos Estaduais de Educação (CEE/MEC).
* **Jornada Real do Aluno:**
  1. **Captação / Lead:** Tirar dúvidas sobre validade do diploma (MEC/Diário Oficial), preços, formas de pagamento e link de matrícula.
  2. **Matrícula / Documentação:** Paga a taxa de matrícula e envia documentos obrigatórios (RG/CNH, CPF, Comprovante de Residência, Histórico/Certificado Escolar anterior e Selfie/Biometria).
  3. **Validação pela Secretaria:** Auditoria humana/IA dos documentos.
  4. **Preparação & Avaliação (Exame Final):** Acesso a apostilas/simulado e agendamento/realização da avaliação oficial.
  5. **Homologação & Certificação:** Lançamento de notas em ata, publicação no Diário Oficial / GDAE / CEE e emissão do Histórico e Certificado de Conclusão.

### 1.2 Redefinição Canônica do Ciclo de Estados (Substituindo `active`)
O termo genérico `active` foi descontinuado por induzir a erros conceituais de LMS. A nova régua de estados de negócio para a persona `student` é:

| Status Canônico | Significado Real no Negócio | Ações do Aluno / Bot |
| :--- | :--- | :--- |
| `lead` | Interessado captado que ainda não concluiu o pagamento da matrícula. | Consulta preços (`/public/pricing`), regras, prazos e recebe link de checkout (`/public/lead/checkout`). |
| `enrollment` | Matrícula paga. Fase obrigatória de preenchimento cadastral e envio de documentos. | Envio de fotos de RG, comprovante de residência e selfie biométrica. |
| `academic` *(substituto de active)* | Documentos homologados pela secretaria. Aluno regularizado para prova e certificação. | Acesso a materiais de apoio/simulados e agendamento da prova final. |
| `exam` | Prova agendada ou em realização/correção pela banca. | Consulta de data/local da prova ou acompanhamento de nota da ata. |
| `homologation` | Prova aprovada. Processo tramitando para publicação no Diário Oficial / GDAE. | Acompanhamento do status de homologação e código de autenticidade. |
| `graduated` | Concluinte com certificado e histórico emitidos e registrados. | Download de 2ª via digital, validação de QR Code do certificado e indicação de novos alunos. |

---

## 2. Mapeamento Completo das Lógicas Públicas (`/api/v1/public/*`)

Toda a lógica acessível sem token de autenticação (pública ou por segredo de link efêmero) migrará para o escopo `/api/v1/public/*` hospedado no **Cloudflare Worker**:

```http
GET  /api/v1/public/health
GET  /api/v1/public/pricing
GET  /api/v1/public/referral/{ref}
POST /api/v1/public/auth/check
POST /api/v1/public/lead/capture
GET  /api/v1/public/lead/pix/{token}
POST /api/v1/public/turnstile/verify
```

### 2.1 Especificação Detalhada de Cada Endpoint Público

#### 1. `GET /api/v1/public/pricing`
* **Finalidade:** Retorna a tabela oficial de preços de vitrine e regras de parcelamento.
* **Cache:** Edge Cache no Cloudflare (`s-maxage=300, stale-while-revalidate=600`).
* **Parâmetros:** `ref` (opcional — caso haja condição especial de parceiro).
* **Payload de Resposta:**
  ```json
  {
    "pix": "1615.00",
    "card": {
      "installments": 12,
      "installment": "159.90",
      "total": "1918.80"
    },
    "promo_pix": "999.00",
    "promo_card": {
      "installments": 12,
      "installment": "99.00",
      "total": "1188.00"
    },
    "anchor_full": "1615.00",
    "commission_direct": "100.00"
  }
  ```

#### 2. `GET /api/v1/public/referral/{ref}`
* **Finalidade:** Resolve o slug ou código do promotor/polo para exibir o selo de indicação na landing page ou no bot ("Você está sendo atendido por indicação de [Nome]").
* **Payload de Resposta:**
  ```json
  {
    "name": "João",
    "hub": "Polo Central",
    "valid": true
  }
  ```

#### 3. `POST /api/v1/public/auth/check`
* **Finalidade:** Consulta se um telefone ou CPF já possui cadastro no sistema.
* **Comportamento de Segurança (Convention §5):** Vaza honestamente a existência (`found: true/false`, `registered: true/false`). Isso permite que a IA ou o frontend decida imediatamente entre conduzir o fluxo de login/OTP ou iniciar o acolhimento de novo lead.
* **Payload de Requisição:** `{"phone": "+5511999998888", "auto_capture": false}`

#### 4. `POST /api/v1/public/lead/capture` (Zero-Friction Inbound)
* **Finalidade:** Criação instantânea de conta de lead quando um número novo entra em contato via WhatsApp ou landing page.

#### 5. `GET /api/v1/public/lead/pix/{token}`
* **Finalidade:** Retorna dados para renderização da tela de pagamento PIX (QR Code PNG e Copia-e-Cola) usando o token opaco do link curto enviado pelo bot (`/lead/checkout/<token>`). Não exige autenticação por usar token secreto como capability URL.

#### 6. `POST /api/v1/public/turnstile/verify`
* **Finalidade:** Validação do desafio anti-bot Cloudflare Turnstile antes de emissões de checkout ou envios sensíveis em navegadores web.

---

## 3. Auditoria do Fluxo Atual de Criação de Usuário (Telefone Desconhecido)

Abaixo está o raio-x exato de como o código atual do monólito (`users/roles/lead/service.py` e `users/auth/service.py`) reage quando um telefone inexistente faz contato:

```
                  ┌─────────────────────────────────────────────────────────┐
                  │ 1. Telefone Desconhecido entra via WhatsApp ou Webhook  │
                  └────────────────────────────┬────────────────────────────┘
                                               │
                                               ▼
                  ┌─────────────────────────────────────────────────────────┐
                  │ 2. Normalização e Validação E.164                       │
                  │    • validation.validate_phone("+5511999998888")        │
                  │    • Verificação WhatsApp ativo (best-effort)           │
                  └────────────────────────────┬────────────────────────────┘
                                               │
                                               ▼
                  ┌─────────────────────────────────────────────────────────┐
                  │ 3. Busca no Banco de Dados                              │
                  │    • profiles.find_by_phone(resolved_phone)             │
                  │    • Resultado: None (Usuário Novo)                     │
                  └────────────────────────────┬────────────────────────────┘
                                               │
                                               ▼
                  ┌─────────────────────────────────────────────────────────┐
                  │ 4. Resolução de Promotor / Hub                          │
                  │    • _resolve_promoter(ref)                             │
                  │    • Se ref vazio: Promotor Padrão (Hub Central)        │
                  └────────────────────────────┬────────────────────────────┘
                                               │
                                               ▼
                  ┌─────────────────────────────────────────────────────────┐
                  │ 5. Transação Atômica de Criação (users.auth.register)   │
                  │    a) User.objects.create_user() (Gera UUID external_id)│
                  │    b) Profile.objects.create(user, phone, name)         │
                  │    c) Address vazio vinculado ao profile                │
                  │    d) Documents vazio vinculado ao user                 │
                  │    e) Role 'lead' associada ao user                     │
                  └────────────────────────────┬────────────────────────────┘
                                               │
                                               ▼
                  ┌─────────────────────────────────────────────────────────┐
                  │ 6. Provisionamento de Negócio (users.roles.lead)        │
                  │    a) Criação da entidade Lead(status=PENDING)          │
                  │    b) lead.lock_pricing(ref): Congela snapshot de preço │
                  │       (impede reajustes ou alterações durante o funil)  │
                  │    c) Salva atribuição (UTM source, campaign, IP)       │
                  └────────────────────────────┬────────────────────────────┘
                                               │
                                               ▼
                  ┌─────────────────────────────────────────────────────────┐
                  │ 7. Efeitos Colaterais & Notificações                    │
                  │    a) Notifica promotor: "Novo lead captado"            │
                  │    b) Se Web/App: Dispara OTP via WhatsApp              │
                  │    c) Se WhatsApp Inbound (Dify): Não dispara OTP extra │
                  │       (a sessão no WhatsApp já valida a posse do número)│
                  └─────────────────────────────────────────────────────────┘
```

---

## 4. Oportunidades de Otimização na Migração para o Cloudflare Edge

1. **Eliminação de Round-trips Desnecessários:** No modelo legado, o Django consulta o WhatsApp, consulta o banco, consulta o promotor e trava várias tabelas em transações lentas. No Cloudflare Worker, a consulta de existência é feita via KV/D1 em <5ms.
2. **Separação de Contexto no Dify:** O bot não precisa de acesso a rotas administrativas ou de alunos matriculados. Quando o contato chega, a primeira verificação no Worker informa:
   - Se novo: Dify opera com as tools de `/api/v1/public/*` (apresentação, preços, tirar dúvidas, cadastro e checkout).
   - Se já é aluno: Dify carrega as tools específicas do status (`enrollment` para envio de documentos ou `academic` para agendamento de prova).

---

## 5. Próximos Passos Imediatos de Execução

1. **Persistência no Git:** Salvar esta especificação na branch principal e no repositório GitHub.
2. **Notificação de Governança:** Informar o *Plannotator Reviewer*, o *Arquiteto de Identidade* e o *Arquiteto de APIs*.
3. **Construção do Worker Cloudflare:** Criar a estrutura do Worker contendo os endpoints públicos `/api/v1/public/pricing` e `/api/v1/public/auth/check`.
4. **Conexão no Dify:** Configurar o Custom Tool do Dify para consumir o novo contrato público na borda.
