# Plano Estratégico de Marketing, Growth e Aquisição — Supletivo Brasil (supletivo.net.br)

**Data de Elaboração:** 16 de Novembro de 2026  
**Responsável:** Diretor de Marketing & Growth Operacional (AI Marketing Skills Framework)  
**Ecossistema:** `supletivo.net.br` | `app.supletivo.net.br` | `backend.supletivo.net.br` | `promotor.supletivo.net.br`  

---

## 1. Visão Geral & North Star Metric

O **Supletivo Brasil** tem como propósito transformar vidas através da conclusão acelerada do Ensino Fundamental e Médio (EJA) 100% online, com certificação oficial autorizada e amparada pela LDB e Diário Oficial.

### Unit Economics de Aquisição (Target 2026/2027)
- **Ticket Médio (Pix)**: R$ 999,00 (promocional/ref) / R$ 1.615,00 (tabela).
- **Ticket Médio (Cartão)**: 12x de R$ 99,00 (R$ 1.188,00 bruto).
- **CAC Alvo (Meta Ads / Google Ads)**: ≤ R$ 160,00 por aluno pago.
- **ROAS Blended Alvo**: ≥ 5.5x no Pix e ≥ 6.8x no LTV de Cartão.
- **North Star Metric**: **Matrículas Homologadas Pagas / Semana** (Taxa de ativação do status `PENDING` -> `PAID` -> `ACTIVE`).

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       FUNIL INTEGRADO SUPLETIVO BRASIL                      │
├─────────────────┬──────────────────────┬────────────────────────────────────┤
│ 1. AQUISIÇÃO    │ 2. CONVERSÃO BORDA   │ 3. HANDOFF & RESGATE               │
│ (Tráfego & Ads) │ (Landing Page)       │ (App & WhatsApp)                   │
├─────────────────┼──────────────────────┼────────────────────────────────────┤
│ • Meta Ads      │ • Sofia Omnibar      │ • Handoff OTP seguro               │
│ • Google Search │ • WhatsApp First     │ • Ghost Lead Recovery (<10 min)    │
│ • Promotores    │ • Validação CPF LDB  │ • InfinitePay Checkout             │
│ • SEO Orgânico  │ • Credencial 3D      │ • Régua PIX / Cartão Pendente      │
└─────────────────┴──────────────────────┴────────────────────────────────────┘
```

---

## 2. Auditoria CRO da Landing Page (`supletivo.net.br`)

Auditoria executada em 16/11/2026 utilizando o motor `cro_audit.py` (AI Marketing Skills / Eric Siu) calibrado para o segmento de Educação no Brasil:

| Dimensão CRO | Pontuação (0-100) | Diagnóstico Operacional | Ação Recomendada |
| :--- | :---: | :--- | :--- |
| **Headline Clarity** | **60/100** | O H1 atual (*"Você parou. Mas não acabou."*) é emocionalmente forte, mas em testes de 5s omite o ganho prático imediato acima da dobra no mobile. | Testar variante com promessa direta: *"Conclua seu Ensino Médio ou Fundamental pelo celular em tempo recorde e com certificado válido pelo MEC."* |
| **CTA Visibility** | **75/100** | 6 CTAs bem distribuídos com botões de alto contraste (*Quero meu diploma*). | Adicionar micro-reforço de segurança abaixo do botão: *"Sem mensalidades surpresa · Início imediato"*. |
| **Social Proof** | **75/100** | 66 menções/elementos de prova e 26 selos. Falta quantificação numérica agregada no viewport inicial. | Inserir badge dinâmico: *"Mais de 3.200 alunos certificados em todo o Brasil · Nota 4.9/5"*. |
| **Urgency** | **50/100** | Urgência discreta (*"hoje"*). Falta o gatilho de fechamento de ciclo de matrícula/homologação. | Sincronizar o banner flutuante com contagem regressiva da turma atual: *"Turma de Homologação Expressa: Últimas 14 vagas com bolsa de R$ 99/mês"*. |
| **Trust Signals** | **90/100** | Excelente: conformidade com LDB, Diário Oficial, CEE, LGPD e garantia incondicional de 7 dias. | Manter e reforçar ícone do Diário Oficial ao lado do botão de avanço na Omnibar. |
| **Form Friction** | **65/100** | Sofia Omnibar tem excelente usabilidade (1 campo por vez), mas solicitar CPF no passo 2 causa abandono se o usuário não entender a exigência legal. | Otimizar micro-copy do passo 2: *"Exigência legal do MEC para checagem de elegibilidade da bolsa"*. |
| **Mobile & Speed** | **95/100** | Responsividade impecável, Cloudflare Edge, Speculation Rules ativas. | Otimizar bundling de CSS inline (142KB) para estilos cacheados em borda. |
| **PONTUAÇÃO GLOBAL** | **71.5 / 100** | **Grau B- (Top Quartile Educação)** | **Potencial de aumento de conversão: +28% a +42% após ajustes.** |

---

## 3. Matriz de Aquisição Paga & Autoresearch de Criativos

Em coordenação com **Tráfego e Performance** e **Copywriter de Conversão**, estruturamos 3 clusters de criativos baseados em gatilhos psicológicos profundos do público EJA:

### Cluster 1: Oportunidade Profissional & Emprego (Ângulo Racional/Necessidade)
* **Público**: Trabalhadores operacionais, balconistas, operadores de telemarketing, motoristas de aplicativo.
* **Dor Central**: *"Perdi a oportunidade de promoção / vaga de emprego com carteira assinada porque não tinha o comprovante do Ensino Médio."*
* **Hooks de 3s (Vídeo/Shorts/Reels)**:
  1. *"Você sabia que mais de 70% das vagas de emprego exigem Ensino Médio completo logo na primeira triagem?"*
  2. *"Quantas vezes você teve que mentir no currículo ou fugir da pergunta 'você terminou os estudos'?"*
  3. *"Com apenas 30 minutos por dia no celular, seu diploma do Ensino Médio fica pronto."*
* **CTA**: *"Consulte sua elegibilidade gratuita pelo WhatsApp."*

### Cluster 2: Concursos Públicos, CNH e Segurança Familiar (Ângulo Alavancagem)
* **Público**: Homens e mulheres de 24 a 45 anos que desejam estabilidade (concursos da prefeitura, polícia, correios, vigilância armada, técnico de enfermagem).
* **Dor Central**: *"Não consigo prestar o concurso da minha cidade nem tirar certas categorias de CNH por falta de estudo."*
* **Hooks de 3s**:
  1. *"Concursos de nível médio pagam salários de R$ 3.000 a R$ 5.500. Mas você precisa do certificado registrado."*
  2. *"Não deixe uma vaga pública passar por falta de um documento que você pode resolver ainda este mês."*
* **CTA**: *"Veja como funciona a homologação oficial no Diário Oficial."*

### Cluster 3: Superação & Orgulho Pessoal (Ângulo Emocional/Dignidade)
* **Público**: Adultos 35+ que tiveram que trabalhar cedo para sustentar a família ou mães que pausaram os estudos pelos filhos.
* **Dor Central**: *"Vergonha de não ter estudado e o desejo de dar o exemplo para os filhos."*
* **Hooks de 3s**:
  1. *"Você não abandonou a escola porque quis. Você teve que colocar comida na mesa."*
  2. *"O seu passado de luta não define o seu futuro. Você parou, mas a sua história não acabou."*
* **CTA**: *"Dê esse orgulho para você e para a sua família hoje."*

---

## 4. Sales Pipeline & Ghost Lead Recovery (WhatsApp Nudge)

O maior ponto de atrito em funis educacionais é a hesitação entre fornecer o telefone e digitar o CPF/dados confidenciais.

### Arquitetura de Resgate de Lead Incompleto (Ghost Recovery)
Como o endpoint `/api/v1/clients/auth/check` já recebe o número de WhatsApp no primeiro passo da Omnibar, ativamos a seguinte régua automática via **Whatsapp / Chatwoot**:

```
[Visitante digita WhatsApp na Sofia Omnibar]
                  │
                  ▼
   [Completou CPF e foi pro App?]
        ├── SIM ──► Fluxo de Matrícula Normal no App
        └── NÃO ──► AGUARDAR 8 MINUTOS
                         │
                         ▼
             [Mensagem 1 - Sofia WhatsApp]
             "Oi! Aqui é a Sofia do Supletivo Brasil.
              Vi que você iniciou sua consulta de elegibilidade,
              mas não concluiu a verificação.
              Ficou alguma dúvida sobre o certificado do MEC ou
              as condições de pagamento? Posso te ajudar por aqui!"
                         │
                         ▼ (Após 3 horas se sem resposta)
             [Mensagem 2 - Oferta de Bolsa Exclusiva]
             "Liberamos uma condição especial de homologação rápida
              para a turma desta semana: 12x de R$ 99 sem juros.
              Quer que eu reserve a sua vaga?"
```

---

## 5. Parcerias de Campo & Programa de Promotores (`promotor.supletivo.net.br`)

O tráfego pago digital deve ser complementado por aquisição física e comunitária de alta confiança:

1. **Autoescolas & Centros de Formação de Condutores (CFC)**:
   - Alunos que reprovam na exigência de escolaridade ou precisam de Ensino Fundamental/Médio para CNH profissional (C, D, E).
   - Comissão por aluno matriculado: R$ 150,00 para o instrutor/atendente.
2. **Empresas de Segurança, Vigilância e Facilities**:
   - Empresas que exigem Ensino Médio para seus colaboradores poderem assumir postos mais remunerados.
   - Parceria corporativa de qualificação com link de desconto (`?ref=empresaX`).
3. **Lideranças Comunitárias e Religiosas**:
   - Divulgação institucional em murais de igrejas e associações de bairro com foco em resgate social e empregabilidade.

---

## 6. Diretrizes Anti-Slop de Conteúdo (Humanizer Gate 90+)

Todo e qualquer material produzido (seja anúncio, script de vídeo, e-mail ou WhatsApp) passa obrigatoriamente pela validação do checklist humanizador:
- **Zero Construções de Negação Paralela**: Proibido usar *"Não é apenas um curso, é uma transformação"*. Diga o que é: *"Você estuda no celular e recebe o diploma com publicação no Diário Oficial"*.
- **Vocabulário Proibido**: Nada de *"revolucionário"*, *"ecossistema"*, *"holístico"*, *"divisor de águas"*, *"imperdível"*, *"transformador"*.
- **Tom Operacional**: Falar a linguagem da pessoa trabalhadora brasileira: simples, respeitosa, realista, direta ao ponto e sem falsas promessas de diploma sem estudo.

---


---

## 7. Validacao Tecnica do Funil e Dicionario de Telemetria (Contribuicao: Funil)

### 7.1. Auditoria de Brechas Criticas
1. **Brecha de PII no dataLayer (track.ts e LeadCaptureModal.astro)**:
   - Risco: Envio de telefone em texto claro viola LGPD e politicas do GA4 e Meta Pixel.
   - Correcao obrigatoria: Sanitizar para hash SHA-256 ou formato mascarado: { is_existing: true, phone_masked: maskPhone(digits) }.
2. **Cegueira nos Passos Intermediarios da Omnibar**:
   - Implementar disparos explicitos: lead_step_phone_completed (Passo 1 concluido) e lead_step_cpf_completed (Passo 2 concluido) para auditar a taxa de conversao interna do micro-funil.

### 7.2. Dicionario Unificado de Eventos (LP -> App -> Checkout)
- **LP (supletivo.net.br)**: view_landing_page, cta_click, lead_modal_opened, lead_step_phone_completed, lead_step_cpf_completed, lead_capture_submitted.
- **Autenticacao (app.supletivo.net.br)**: otp_screen_viewed, otp_resend_clicked, otp_verified.
- **Checkout InfinitePay**: initiate_checkout, payment_method_selected, pix_code_generated, pix_code_copied, card_payment_failed, purchase.
- **Ativacao**: enrollment_step_completed, student_activated.
