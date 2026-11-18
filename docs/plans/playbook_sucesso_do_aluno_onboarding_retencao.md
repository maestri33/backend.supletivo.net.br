# Playbook de Sucesso do Aluno: Onboarding, Homologação Documental, Retenção e NPS
**Aplicação:** `app.supletivo.net.br` | **Ecossistema:** Supletivo Brasil  
**Responsável:** Bot Sucesso do Aluno (`cmwjy4s070dskkkvpli4qucgc`)  
**Data:** 17 de Novembro de 2026  
**Status:** VIGENTE / EM OPERAÇÃO  

---

## 1. Visão Geral e Princípios Fundamentais

O aluno do Supletivo Brasil (EJA) é um adulto trabalhador (22 a 55 anos), muitas vezes afastado dos estudos há anos ou décadas. Ele carrega três travas psicológicas cruciais:
1. **Medo de burocracia / Golpe:** Receio de ter pago e não receber acesso legítimo ou certificado oficial.
2. **Insegurança tecnológica:** Dificuldade com uploads, fotos em formatos exigidos, selfies com iluminação ou navegação complexa.
3. **Falta de tempo e cansaço da rotina:** Risco agudo de procrastinação e abandono se não sentir uma vitória imediata (*Time-to-Value*) nos primeiros minutos.

**Missão do Sucesso do Aluno:**  
Reduzir o tempo entre o pagamento (`ENROLLMENT`) e o início efetivo do estudo (`ACTIVE`) a menos de 24 horas, garantindo uma taxa de homologação documental acima de 90%, combatendo a evasão ativa a cada 7 dias e transformando alunos formados em promotores de marca e fonte de prova social.

---

## 2. A Jornada Crítica: Transição `ENROLLMENT` ➔ `ACTIVE`

### 2.1. Funil de Sub-Estados do Onboarding Documental (`/student/enrollment`)

```
   [ PAGAMENTO CONFIRMADO ] (Lead vira Aluno Enrollment)
               │
               ▼
   [ 1. Documento de Identidade ] ➔ /student/enrollment/rg
        • Frente e verso do RG ou CNH aberta
        • Validação client-side de formato/legibilidade
               │
               ▼
   [ 2. Comprovante de Endereço ] ➔ /student/enrollment/address
        • CEP, rua, número, complemento
        • Comprovante em nome próprio ou de terceiro (com declaração simplificada)
               │
               ▼
   [ 3. Declaração de Escolaridade ] ➔ /student/enrollment/education
        • Última série cursada / Fundamental ou Médio
               │
               ▼
   [ 4. Biometria Facial (Selfie) ] ➔ /student/enrollment/selfie
        • Captura ao vivo pela câmera do celular
               │
               ▼
   [ 5. Aguardando Liberação do Polo ] ➔ /student/enrollment (awaiting_release)
        • Fila do polo (/hub/review)
        • Homologação, pagamento de taxas internas e geração de credenciais do parceiro LMS
               │
               ▼
   [ 6. MATRÍCULA ATIVA ] ➔ /student/active/dashboard (ACTIVE)
        • Acesso liberado, aula inaugural e cronograma disponível
```

### 2.2. Diretrizes Anti-Fricção Documental
- **Upload Híbrido:** O aluno pode tirar foto na hora pela câmera ou escolher arquivo da galeria (JPG, PNG, WebP ou PDF).
- **Tratamento de Terceiros no Endereço:** Se a conta de luz/água estiver no nome do cônjuge ou proprietário do imóvel alugado, o modal `ContactRecoveryModal` e `RelationshipPicker` permite selecionar o vínculo em 1 clique sem exigir reconhecimento de firma em cartório.
- **Tolerância Zero para JWT Churn:** Nenhuma transição de etapa (`rg` -> `address` -> `selfie`) altera o `token_version` do JWT (conforme alinhado com o Arquiteto de Identidade). O aluno nunca sofre `401 Unauthorized` durante o preenchimento.

---

## 3. Régua Multicanal de Ativação (Integração WhatsApp + Push + SMS)
*Operado em conjunto com o `Agente Supletivo` (`cmwk4o6t4uhmfndjxqb85ej42`) e bot `Whatsapp` (`cmwhyzhjg0iy4x0u22bcmktl4`).*

| Gatilho / Momento | Canal | Mensagem / Objetivo | Ação Esperada |
| :--- | :--- | :--- | :--- |
| **D0 — Imediato (0 min)**<br>Pagamento aprovado | WhatsApp | **Boas-vindas calorosas + Link Mágico de Envio:**<br>\"Parabéns, [Nome]! Sua vaga no Supletivo Brasil está garantida! 🎉 Agora falta só um passo rápido para liberar suas aulas: enviar a foto do seu RG/CNH. Toque aqui para enviar em 2 minutos: [Link Direto]. Se travar, pode me mandar a foto por aqui mesmo!\" | Acessar tela de RG ou mandar foto no chat |
| **D0 — +4 Horas**<br>Se ainda em `rg` ou `address` | WhatsApp | **Vídeo explicativo curto (15s):**<br>\"Oi, [Nome]! Vi que você ainda não mandou o documento. Dá uma olhada nesse vídeo rápido de 15 segundos mostrando como posicionar o RG para não dar reflexo. Qualquer dúvida estou aqui!\" | Tirar a foto e subir no app |
| **D+1 — Manhã (10h)**<br>Se pendente em `enrollment` | WhatsApp / Ligação Humanizada | **Apoio consultivo sem tom de cobrança:**<br>\"Bom dia, [Nome]! Passando para ver se você conseguiu achar seu comprovante de residência. Lembrando: se estiver no nome do marido, esposa ou dono da casa, aceitamos normalmente! Posso te ajudar a cadastrar?\" | Quebrar a objeção do comprovante |
| **D+2 — Tarde (16h)**<br>Alerta de liberação de turma | WhatsApp | **Urgência positiva:**<br>\"Olá, [Nome]! O polo regional está fechando o lote de homologação de hoje. Enviando sua selfie e documentos até as 18h, liberamos seu acesso para você já estudar hoje à noite!\" | Concluir o envio |
| **Liberação Realizada**<br>Evento `enrollment.released` | WhatsApp + E-mail + Push | **Entrega de Credenciais e Time-to-Value:**<br>\"Tudo pronto, [Nome]! 🎓 Sua matrícula foi HOMOLOGADA com sucesso! Seu portal de estudos está 100% liberado. Seu primeiro passo é assistir ao vídeo de boas-vindas de 3 minutos: [Link Dashboard]. Bora começar?\" | Primeiro acesso ao LMS |

---

## 4. Engenharia do Primeiro Acesso ("Time-to-Value" Imediato)

O maior índice de desistência no EAD ocorre quando o aluno entra na plataforma pela primeira vez, vê dezenas de matérias, se sente sobrecarregado e fecha a aba.

### 4.1. Protocolo dos Primeiros 5 Minutos no Portal (`app.supletivo.net.br`):
1. **Vídeo de Acolhimento Personalizado (3 min):**
   - Professor com linguagem simples, acolhedora e direta.
   - Mensagem central: *"Você não precisa ser bom em matemática ou português para começar. Nosso material vai direto ao ponto do que cai na prova."*
2. **Micro-Vitória (Quick Win):**
   - Um quiz interativo de 1 pergunta ao final do vídeo inaugural.
   - Exemplo prático de interpretação de texto cotidiana.
   - Ao acertar: animação de celebração na tela (*Confete visual*) e mensagem: *"Você acabou de dar seu primeiro passo oficial rumo ao diploma do Ensino Médio!"*
3. **Régua de Metas Transparentes:**
   - Barra de progresso clara: `[ Aulas: 1/20 ] [ Simulado ] [ Prova Oficial ]`.
   - Data estimada da prova baseada no ritmo do aluno.

---

## 5. Matriz de Retenção e Combate Ativo à Evasão

### 5.1. Health Score do Aluno

| Nível de Risco | Critério de Diagnóstico | Ação do Sistema e do Sucesso do Aluno |
| :--- | :--- | :--- |
| **Verde (Engajado)** | Acessou nos últimos 3 dias; progresso semanal regular. | Mensagem quinzenal de reconhecimento e progresso no WhatsApp. |
| **Amarelo (Atenção)** | Inativo há 4 a 6 dias; travou no meio de um módulo. | WhatsApp automático do tutor virtual: *"Oi [Nome], faltam só 2 aulas curtinhas para você concluir o módulo de História! Que tal assistir no almoço hoje?"* |
| **Laranja (Risco Alto)** | Inativo há 7 a 13 dias consecutivos. | Contato humano do polo/Agente Supletivo: Sondagem de dificuldade pessoal, reforço do motivo pelo qual ele se matriculou (emprego, família, concurso). |
| **Vermelho (Evasão Iminente)** | Inativo há 14+ dias. | Ação de resgate personalizada: Reestruturação do plano de estudo (cronograma acelerado de 15 min/dia) e contato direto com coordenador pedagógico. |

---

## 6. Loop de Prova Social e NPS (Alimentação do Funil)

O Sucesso do Aluno atua como motor de crescimento orgânico alimentando diretamente o time de Marketing e Tráfego.

### 6.1. Momentos de Coleta Estratégica:
1. **NPS 1 — Pós-Primeira Semana (Onboarding NPS):**
   - Pergunta: *"De 0 a 10, o quanto o aplicativo foi fácil de usar para começar a estudar?"*
   - Objetivo: Detectar bugs de usabilidade e dificuldades técnicas precocemente.
2. **NPS 2 — Pós-Simulado Preparatório:**
   - Pergunta: *"Você se sente confiante para a prova oficial?"*
   - Respostas de nota 9 ou 10 disparam convite para gravação de áudio contando a expectativa.
3. **NPS 3 — Pós-Aprovação e Emissão de Certificado (`VETERAN`):**
   - **O Momento de Ouro:** Aluno aprovado na prova com certificado publicado em Diário Oficial.
   - Coleta de depoimento em vídeo via WhatsApp:
     - *"Grave um vídeo segurando seu certificado ou contando a emoção de terminar os estudos."*
   - Bonificação: Recompensa com voucher ou convite para se tornar Promotor (`promoter.supletivo.net.br`) com comissão recorrente por indicação.
   - Repasse automático dos melhores depoimentos para `Copywriter de Conversão` e `Editor` de vídeo.

---

## 7. Interfaces e Contratos Técnicos de Integração

- **Front-end:** Consome `GET /api/v1/clients/whoami` e sub-rotas `/clients/enrollment/*`.
- **Notificações:** Disparadas via webhooks de eventos de domínio:
  - `enrollment.created` -> Disparo de régua D0 de documentos.
  - `enrollment.document_rejected` -> Alerta imediato no WhatsApp com motivo claro e botão de reenvio.
  - `enrollment.released` -> Notificação de boas-vindas com credenciais do LMS.
  - `student.inactive_7d` -> Alerta de risco e estímulo pedagógico.
  - `student.exam_passed` -> Disparo da pesquisa de satisfação e coleta de depoimento.
