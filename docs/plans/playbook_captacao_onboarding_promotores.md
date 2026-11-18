# Playbook de Captação, Onboarding e Ativação de Promotores de Campo
## Ecossistema: `promotor.supletivo.net.br` | `supletivo.net.br` | Backend Supletivo

**Data:** 16 de Novembro de 2026  
**Responsável:** Programa de Promotores  
**Destinatários:** Marketing & Growth, Tráfego & Performance, Copywriter de Conversão, Funil  
**Status:** Operacional / Pronto para Execução  

---

## 1. Tese & Diagnóstico Operacional de Expansão de Campo

O tráfego pago puramente digital (Meta Ads / Google Search) enfrenta saturação gradual de leilão e desconfiança intrínseca no nicho de Educação de Jovens e Adultos (EJA). O público EJA é historicamente cauteloso devido a golpes de diplomas falsos na internet.

A estratégia de **Parcerias de Campo (B2B2C)** resolve essa fricção ao introduzir uma camada de **autoridade física e confiança comunitária imediata**. Quando um atendente de autoescola, um encarregado de segurança/facilities ou um pastor local recomenda o Supletivo Brasil, o lead já entra com taxa de conversão 4x superior à do tráfego frio.

### Unit Economics do Programa de Promotores
- **Oferta ao Aluno:** 12x de R$ 99,00 no cartão de crédito (R$ 1.188,00) ou R$ 999,00 à vista no Pix.
- **Comissão Base do Promotor:** R$ 150,00 por matrícula confirmada paga (status `PAID`).
- **Comissão Escalonada (Nível Ouro / Parcerias Estruturadas):** R$ 200,00 por matrícula paga para parceiros que geram 10+ matrículas/mês.
- **Bônus de Produtividade Semanal:** R$ 500,00 adicionais a cada bloco de 5 alunos pagos na mesma semana (fechamento de sexta-feira).
- **CAC Promotor vs CAC Digital:**
  - CAC Promotor Médio: R$ 150,00 a R$ 200,00 (pago apenas no sucesso / matrícula paga).
  - CAC Ads Médio: R$ 140,00 a R$ 170,00 de mídia + custos de atendimento/recuperação.
  - Vantagem: Risco de aquisição ZERO para a operação (comissão vinculada 100% à liquidação da venda).

---

## 2. Segmentos Prioritários & Propostas de Valor Específicas

### Cluster A: Autoescolas & Centros de Formação de Condutores (CFCs)
* **Público Alvo na Ponta:** Alunos e motoristas que querem obter a Primeira Habilitação ou mudar de categoria para CNH Profissional (Categorias C, D e E para transporte de carga, ônibus, vans escolares e carretas).
* **Fato Jurídico/Regulatório:** O Código de Trânsito Brasileiro (CTB) e cursos de especialização homologados pelo Detran (MOPP, Transporte Coletivo de Passageiros, Cargas Indivisíveis) exigem escolaridade regularizada, e empresas de logística e transporte exigem Ensino Médio completo para contratação CLT.
* **Persona Promotora:**
  1. *Recepcionista / Atendente de Matrícula do CFC:* Ouve diariamente o desabafo de quem não tem o certificado para progredir ou tirar a carteira profissional.
  2. *Instrutor Prático/Teórico:* Possui alta influência sobre os alunos e credibilidade técnica.
* **Pitch de Recrutamento para o Promotor:**
  > *"Você atende gente todo dia que quer crescer na profissão de motorista, mas esbarra na falta do diploma do Ensino Médio. Em vez de dispensar essa pessoa, você indica o Supletivo Brasil pelo seu link ou QR Code no balcão. Ela resolve o ensino médio pelo celular enquanto faz o processo da autoescola, e você recebe R$ 150 a R$ 200 direto no seu Pix toda sexta-feira por cada matrícula."*

---

### Cluster B: Empresas de Segurança Privada, Vigilância e Facilities
* **Público Alvo na Ponta:** Porteiros, controladores de acesso, auxiliares de limpeza, copeiras, vigias noturnos e jardineiros que trabalham em regime 12x36 ou turnos operacionais.
* **Fato Operacional:** Grandes empresas de vigilância e condomínios corporativos exigem Ensino Médio completo em licitações e contratos de prestação de serviços. Além disso, a ascensão funcional (de porteiro para supervisor de segurança, de vigilante patrimonial para gestor de operações) depende do diploma.
* **Persona Promotora:**
  1. *Supervisor Operacional / Inspetor de Área:* Visita os postos de serviço semanalmente, conhece a realidade da tropa e tem voz de comando.
  2. *Líder de RH / Treinamento e Desenvolvimento Local:* Busca qualificar a equipe sem onerar o orçamento da empresa.
* **Pitch de Recrutamento para o Promotor:**
  > *"Quantos colaboradores da sua equipe operacional têm perfil de liderança, mas não podem ser promovidos a supervisores porque pararam nos estudos? Com o Supletivo Brasil, o colaborador estuda no próprio smartphone no tempo livre da escala 12x36, com certificado oficial aceito em qualquer empresa. Você ajuda a equipe a subir de vida e garante uma comissão expressiva via Pix no fechamento de cada semana."*

---

### Cluster C: Lideranças Comunitárias e Religiosas (Igrejas e Bairros)
* **Público Alvo na Ponta:** Fiéis de congregações locais, trabalhadores autônomos, chefes de família e mães solo que não concluíram os estudos por necessidade de sustentar a casa.
* **Fato Social:** O pastor, padre ou líder da associação de moradores é o conselheiro número um das famílias em momentos de desemprego e dificuldade financeira.
* **Mecanismo Exclusivo — Bolsa de Estudos do Promotor:**
  Muitas vezes, a própria liderança comunitária ou voluntária do projeto social também não tem o Ensino Médio. A regra de negócio do backend Supletivo prevê o benefício da **Bolsa Promotor (`pre_matriculado`)**:
  - Ao cadastrar-se sem Ensino Médio, o promotor entra como `pre_matriculado`.
  - Ao bater **3 indicações pagas**, o backend executa automaticamente o enrollment dele como **Bolsista 100% Gratuito** (sem pagar matrícula nem mensalidades).
  - Ao bater **10 indicações pagas**, destrava a liberação da prova final e homologação oficial.
* **Pitch de Recrutamento para a Liderança:**
  > *"Emprego e dignidade começam com o certificado escolar regularizado. Divulgue o Supletivo Brasil no mural da igreja ou nas reuniões da comunidade. A renda das comissões pode ser revertida para o sustento da família do promotor ou para a obra social da congregação. E se quem for divulgar também não tiver terminado os estudos, com apenas 3 indicações matriculadas o curso dele sai 100% de graça."*

---

## 3. Arquitetura Técnica do Funil: Da Landing Page ao Primeiro Link

```
[Visitante: autoescola, vigilante, líder]
                   │
                   ▼
       [promotor.supletivo.net.br]
        (com ou sem ?hub=<polo>)
                   │
                   ▼
      [PromoterLeadCaptureModal]
       ├─ Passo 1: Telefone / WhatsApp (Check Sofia)
       ├─ Passo 2: CPF (Validação Módulo 11)
       ├─ Passo 3: Dados cadastrais + Chave PIX (DICT)
       └─ Passo 4: Escolaridade (Médio completo? S/N)
                   │
                   ▼
     [Backend API: users/roles/candidate]
       ├─ Criação do User + Candidate
       ├─ Vínculo com Hub (Polo local)
       ├─ Se sem Ensino Médio: pre_matriculado = True
       └─ Validação de Chave Pix (Asaas / DICT)
                   │
                   ▼
     [Onboarding & Mini-Capacitação (Training)]
       ├─ Checklist de conduta (Sem falsas promessas)
       ├─ Regra LDB / CEE (Sem claim "MEC direto")
       └─ Aprovação -> Promoter (status = ACTIVE)
                   │
                   ▼
     [Geração Imediata de Ativos de Captação]
       ├─ Link Exclusivo: supletivo.net.br/?ref=<user_uuid>
       ├─ QR Code Dinâmico (PNG/SVG para impressão)
       └─ Pacote de Criativos WhatsApp / Cartaz PDF
```

### 3.1. Validação e Atribuição de Link (`?ref=`)
1. **Frontend Astro (`supletivo.net.br`):**
   - Na chegada do tráfego através de `https://supletivo.net.br/?ref=<UUID>`, o middleware ou script de borda captura o parâmetro `ref`.
   - Armazena nos cookies do navegador:
     `Cookie: supletivo_ref=<UUID>; Path=/; Max-Age=2592000; SameSite=Lax; Secure`
   - Salva espelho no navegador: `localStorage.setItem('supletivo_promoter_ref', '<UUID>')`.
   - Ao interagir com a Sofia Omnibar, o `ref` é enviado na payload de check e de criação de lead:
     `POST /api/v1/clients/auth/check` com `{ phone: "...", ref: "<UUID>" }`.

2. **Backend Supletivo (`users/roles/promoter/service.py`):**
   - Função `validate_ref(ref: str)`:
     - Valida integridade do UUID.
     - Confere se pertence a um `Promoter` com status `ACTIVE` e se não está travado em treinamento (`training_iface.is_locked == False`).
     - Atribui o `Lead` ao `promoter = user`.
   - Quando o lead efetua o pagamento (cartão ou Pix via InfinitePay/Asaas), o webhook dispara `lead.mark_paid`:
     - Cria registro imutável em `finance.Commission`:
       - `source_type`: `Commission.Source.LEAD`
       - `source_external_id`: UUID do Lead
       - `amount`: `Decimal("150.00")` (ou R$ 200 para promotores nível ouro)
       - `status`: `Commission.Status.PENDING`
     - Checagem automática de bolsa: se `promoter.pre_matriculado == True` e atinge 3 indicações, chama `maybe_auto_enroll_bolsista(promoter.user)`.

---

## 4. Regras de Comissionamento, Fechamento e Repasse via Pix

### 4.1. Calendário e Mecanismo de Pagamento
* **Dia do Fechamento:** Toda **sexta-feira às 18:00 (Horário de Brasília)** (`COMMISSION_CLOSING_WEEKDAY = 4`, `COMMISSION_CLOSING_HOUR = 18`).
* **Meio de Pagamento:** Pix automático via API Asaas / InfinitePay no CPF ou chave cadastrada no momento do onboarding.
* **Gatilho de Liberação:** Confirmação do pagamento da matrícula pelo aluno (status `PAID` do pedido). Não depende da conclusão do curso do aluno nem do envio de todos os documentos escolares dele.
* **Segurança e Anti-Fraude:**
  - Auto-indicação proibida: o CPF do promotor não pode ser o mesmo CPF do aluno indicado (detectado automaticamente no backend).
  - Cancelamento/Estorno: caso uma compra em cartão seja cancelada ou estornada dentro do prazo legal de 7 dias antes do fechamento, a comissão muda para `CANCELLED`. Se já paga, gera débito no próximo ciclo (`Commission.Source.REVERSAL`).

### 4.2. Régua de Gamificação e Níveis de Produtividade

| Nível | Matrículas no Mês | Comissão por Matrícula | Bônus Semanal Extra | Benefícios Adicionais |
| :--- | :---: | :---: | :---: | :--- |
| **Bronze** | 1 a 4 alunos | R$ 150,00 | — | Link exclusivo, painel mobile, kit digital de criativos. |
| **Prata** | 5 a 9 alunos | R$ 175,00 | + R$ 500 a cada 5 pagas na semana | Kit impresso enviado ao polo/estabelecimento (display de balcão). |
| **Ouro** | 10+ alunos | R$ 200,00 | + R$ 500 a cada 5 pagas na semana | Contato direto com coordenador de expansão, cartazes personalizados com foto e nome. |

*Exemplo Prático de Ganhos:*
- Um atendente de autoescola que faz **8 matrículas no mês** (sendo 5 delas em uma mesma semana):
  - 8 matrículas x R$ 175,00 = R$ 1.400,00
  - Bônus da semana com 5 matrículas = R$ 500,00
  - **Total no mês:** **R$ 1.900,00** de renda extra líquida via Pix.

---

## 5. Kit de Ativação e Roteiros de Abordagem de Campo

### 5.1. Scripts de Abordagem no WhatsApp (1-a-1)

#### Abordagem 1: Autoescola / CFC (Para o aluno que não tem o Ensino Médio)
> *"Fala, [Nome], beleza? Aqui é o [Seu Nome], da [Nome da Autoescola].*  
> *Lembrei que você comentou sobre querer tirar a carteira profissional / precisava resolver a pendência dos estudos pra avançar no processo.*  
> *A gente fechou uma condição oficial com o Supletivo Brasil: dá pra você concluir o Ensino Fundamental ou Médio direto pelo celular, sem precisar frequentar sala de aula todo dia, e o certificado sai com registro oficial no Diário Oficial e validade em todo o Brasil.*  
> *Está com uma condição de 12x de R$ 99 no cartão ou Pix facilitado.*  
> *Dá uma olhada no link oficial pra ver se você se encaixa: [SEU_LINK_COM_REF]*  
> *Qualquer dúvida me dá um toque aqui que te ajudo!"*

#### Abordagem 2: Supervisor de Facilities / Segurança (Para o colaborador)
> *"Boa tarde, pessoal da equipe!*  
> *Passando pra dar um recado importante sobre evolução de carreira aqui no contrato.*  
> *Muitas vagas de supervisor e encarregado exigem o Ensino Médio completo no currículo. Pra quem ainda não terminou, conseguimos uma parceria com o Supletivo Brasil.*  
> *O curso é 100% online, você estuda pelo smartphone nos dias de folga da escala e o certificado é emitido por escola autorizada pelo Conselho Estadual de Educação com validade para concursos e faculdades.*  
> *A mensalidade sai por 12x de R$ 99 sem pegadinhas.*  
> *Quem tiver interesse em aproveitar a turma desta semana, acessa por esse link: [SEU_LINK_COM_REF]"*

#### Abordagem 3: Liderança Comunitária / Membro de Igreja
> *"A paz / Olá, [Nome]! Tudo bem com a família?*  
> *Sei o quanto a falta de estudo fecha portas de emprego com carteira assinada e concursos na nossa região.*  
> *Estamos apoiando uma iniciativa muito séria com o Supletivo Brasil para ajudar quem teve que parar de estudar no passado a concluir o Ensino Fundamental ou Médio agora.*  
> *É pelo celular, com suporte e certificado oficial reconhecido pelo CEE e pela LDB.*  
> *Se você ou alguém da sua casa quer terminar os estudos ainda este ano por R$ 99 por mês, entra no link da nossa comunidade: [SEU_LINK_COM_REF]"*

---

### 5.2. Conteúdos para WhatsApp Status e Instagram Stories (24h)

#### Card 1: Pergunta Direta (Enquete)
* **Texto no Card:**  
  *\"Você já perdeu uma oportunidade de emprego ou promoção só porque não tinha o diploma do Ensino Médio?\"*  
  [ Opção A: Sim, já perdi ]  
  [ Opção B: Tenho medo disso acontecer ]
* **Legenda / Próximo Story:**  
  *\"Você não precisa voltar pra uma sala de aula de noite. Dá pra concluir pelo celular no seu ritmo, com certificado oficial válido no Diário Oficial. Me chama no direct ou clica no link: [LINK]\"*

#### Card 2: Quebra de Objeção (Sem tempo)
* **Texto no Card:**  
  *\"Trabalha o dia todo e não tem tempo de estudar?*  
  *Com 30 a 40 minutos por dia no seu celular você conclui o Ensino Fundamental ou Médio.*  
  *Condição facilitada: 12x de R$ 99.*  
  *Vagas abertas para a turma de homologação deste mês: [LINK]\"*

---

### 5.3. Especificações para Cartazes Físicos (Autoescolas, Comércios e Murais)

* **Formato Recomendado:** A4 (210 x 297 mm) ou A3 (297 x 420 mm), acabamento em papel Couché 170g ou sulfite adesivo.
* **Layout Estrutural:**
  1. **Topo:** Logo oficial Supletivo Brasil + Selo: *"Validade Nacional · Amparo Lei Federal 9.394/96 (LDB)"*.
  2. **Chamada Principal:**  
     **NÃO DEIXE A FALTA DE ESTUDO TRAVAR SEU FUTURO.**  
     *Conclua o Ensino Fundamental ou Médio pelo seu celular.*
  3. **3 Benefícios Objetivos:**  
     - Estude no seu tempo, onde quiser.  
     - Certificado aceito em Faculdades, CNH Profissional e Concursos Públicos.  
     - Condição de bolsa: a partir de 12x de R$ 99,00.
  4. **Área de Ação Imediata (Bloco de Alta Visibilidade):**  
     - QR Code de 6x6cm direcionando para `https://supletivo.net.br/?ref=<UUID_DO_PROMOTOR>`.  
     - Texto de apoio: *"Aponte a câmera do seu celular para o QR Code ao lado e consulte sua elegibilidade gratuita em 1 minuto."*
  5. **Rodapé:** Dados institucionais e canais oficiais de suporte.

---

## 6. Checklist de Capacitação e Regras Éticas para o Promotor

Para preservar a reputação jurídica e institucional do Supletivo Brasil, o promotor deve passar pelo seguinte crivo de treinamento antes de receber o link ativo:

1. **O que NUNCA dizer (Falsas Promessas / Proibições Rígidas):**
   - ❌ *"Diploma direto pelo MEC sem precisar estudar"* (Falso e crime de estelionato).
   - ❌ *"Compre seu diploma aqui"* (O aluno paga a matrícula, estuda pela plataforma parceira credenciada e faz as avaliações regulatórias).
   - ❌ *"Reconhecido diretamente pelo SISTEC/MEC"* (A competência de autorização de EJA Fundamental e Médio é dos Conselhos Estaduais de Educação - CEE, amparados pela Lei de Diretrizes e Bases 9.394/96).

2. **O que SEMPRE reforçar:**
   - ✅ O curso é flexível, 100% online e amparado na Lei de Diretrizes e Bases da Educação (LDB nº 9.394/96).
   - ✅ O certificado é expedido por escola credenciada junto ao Conselho Estadual de Educação (CEE) com publicação oficial no Diário Oficial.
   - ✅ Válido para prestar concursos públicos, ingressar no ensino superior (faculdades) e exigências profissionais da CLT e Detran.

---

## 7. Próximos Passos & Integração com o Time de Growth

1. **Copywriter de Conversão:** Adaptar as peças gráficas e carrosséis para os formatos finais do Canva/Figma com os tokens do `DESIGN.md`.
2. **Tráfego e Performance:** Estruturar campanha de Meta Ads focada em captar **novos promotores** nas regiões metropolitanas (segmentação: atendentes de autoescolas, líderes de bairro, instrutores).
3. **Equipe de Engenharia / Backend:** Garantir que o endpoint de fechamento semanal (`finance.tasks.process_weekly_closing`) rode pontualmente às sextas 18h e que os alertas sonoros e WhatsApp de "Comissão Liberada" sejam disparados para os promotores.
