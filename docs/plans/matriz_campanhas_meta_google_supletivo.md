# Matriz Operacional de Mídia de Performance & Campanhas — Supletivo Brasil (supletivo.net.br)

**Data de Emissão:** 16 de Novembro de 2026  
**Autor:** Especialista em Tráfego e Performance  
**Destinatário:** Diretor de Marketing & Growth Operacional (`shared/plans/plano_marketing_growth_supletivo.md`)  
**Ecosistema:** Meta Ads (Facebook/Instagram), Google Ads (Search & PMax), Cloudflare Edge Tracking & CAPI  

---

## 1. Unit Economics, Modelagem de CAC e Metas de Eficiência

Avaliamos e aprovamos integralmente as premissas econômicas do plano de growth:
- **Ticket Médio Pix:** R$ 999,00
- **Ticket Médio Cartão:** 12x de R$ 99,00 (R$ 1.188,00 bruto)
- **CAC Teto Operacional:** R$ 160,00
- **Margem de Mídia sobre Ticket:** 16,0% no Pix e 13,4% no Cartão (margem de segurança excelente para escala).
- **ROAS Blended Alvo:** ≥ 5.5x (Pix) e ≥ 6.8x (LTV Cartão).
- **North Star Metric:** Matrículas Homologadas Pagas / Semana (`PENDING` -> `PAID` -> `ACTIVE`).

### Modelagem do Funil de Conversão e Sensibilidade de CAC

| Etapa do Funil | Taxa Conversão Estimada | Custo Unitário Estimado | Métrica de Controle |
| :--- | :---: | :---: | :--- |
| **Impressão -> Clique (CTR)** | 1.8% a 3.2% | - | Relevância do gancho nos primeiros 3s |
| **Clique -> Aterrissagem LP (Visitante)** | 88% a 94% | CPC: R$ 1,30 a R$ 2,40 | Cloudflare Edge 0ms (Speculation Rules) |
| **Visitante LP -> Sofia Omnibar (Passo 1 Tel)** | 9.0% a 13.5% | CPL (Lead Tel): R$ 11,00 a R$ 19,00 | Engajamento no Hero e Omnibar |
| **Lead Tel -> CPF Validado / Acesso ao App** | 50.0% a 62.0% | Custo Lead Qualificado: R$ 22,00 a R$ 38,00 | Resgate Ghost Lead (<8 min) |
| **Acesso ao App -> Matrícula Paga (Checkout)** | 18.0% a 26.0% | **CAC Final: R$ 115,00 a R$ 155,00** | InfinitePay Checkout + WhatsApp Nudge |

**Conclusão Operacional:** Mantendo o CPC médio entre R$ 1,30 e R$ 2,40 e a conversão global de visita em venda entre 1,1% e 1,6%, a operação opera confortavelmente **abaixo do teto de CAC de R$ 160,00**.

---

## 2. Estratégia de Dimensionamento e Alocação de Verba (Budget Rollout)

Adotamos a alocação progressiva em 3 fases para calibrar algoritmo, sinais de CAPI e evitar queima de orçamento:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   DISTRIBUIÇÃO DA VERBA POR CANAL                      │
├───────────────────────┬───────────────────────┬────────────────────────┤
│ FASE 1: VALIDAÇÃO     │ FASE 2: TRAÇÃO        │ FASE 3: ESCALA         │
│ (R$ 10.000 / mês)     │ (R$ 25.000 / mês)     │ (R$ 60.000 / mês)      │
├───────────────────────┼───────────────────────┼────────────────────────┤
│ • Meta Ads: 65%       │ • Meta Ads (CBO): 55% │ • Meta Ads (Adv+): 50% │
│   (R$ 216/dia)        │   (R$ 458/dia)        │   (R$ 1.000/dia)       │
│ • Google Search: 35%  │ • Google Search: 30%  │ • Google Ads: 35%      │
│   (R$ 117/dia)        │   (R$ 250/dia)        │   (R$ 700/dia)         │
│ • Remarketing: -      │ • Remarketing: 15%    │ • Retargeting Multi:15%│
│   (incluso no Meta)   │   (R$ 125/dia)        │   (R$ 300/dia)         │
└───────────────────────┴───────────────────────┴────────────────────────┘
```

### Projeção de Resultados por Fase:
- **Fase 1 (Validação - 15 dias)**: ~62 a 70 matrículas pagas | Faturamento: ~R$ 65.000 | CAC real previsto: ~R$ 145,00.
- **Fase 2 (Tração - 30 dias)**: ~165 a 180 matrículas pagas | Faturamento: ~R$ 175.000 | CAC real previsto: ~R$ 140,00.
- **Fase 3 (Escala - 30 dias)**: ~400 a 440 matrículas pagas | Faturamento: ~R$ 420.000 | CAC real previsto: ~R$ 138,00 a R$ 150,00.

---

## 3. Matriz de Campanhas no Meta Ads (Facebook & Instagram)

### Estrutura e Nomenclatura Padronizada
- Convenção: `[SB]_[OBJ]_[CANAL]_[SEGMENTO]_[FASE]`
- Otimização inicial: Evento `Lead` (Passo 1 Sofia Omnibar). Após 50 compras semanais registradas via CAPI, migração do CBO para `Purchase` com atribuição de 7 dias clique / 1 dia visualização.

### CAMPANHA 01: `[SB]_CONV_META_AQUISICAO_TOPO_MEIO_CBO`
* **Tipo de Orçamento**: CBO (Advantage Campaign Budget)
* **Objetivo de Campanha**: Conversões / Vendas
* **Conjuntos de Anúncios (Ad Sets)**:

#### Ad Set 1.1 — Cluster 1: Empregabilidade & Renda (Necessidade Imediata)
- **Público**: Homens e Mulheres, 21 a 48 anos, Brasil.
- **Interesses / Sinais**: Vagas de emprego, LinkedIn, Catho, InfoJobs, Atendimento ao cliente, Varejo, Operador de caixa, Repositor, Primeiro Emprego.
- **Exclusões**: Compradores (`Purchase`) últimos 180 dias, Alunos ativos (`app.supletivo.net.br`).
- **Criativos Alocados**:
  - `VID_EMP_01` (9:16): *“70% das vagas exigem Ensino Médio logo na triagem. Pare de perder promoção por falta de documento.”*
  - `VID_EMP_02` (9:16): *“Mentir no currículo ou fugir da pergunta da entrevista? Resolva seu diploma pelo celular.”*
  - `IMG_EMP_01` (1:1 / 4:5): Print simulado de vaga de emprego com salário de R$ 2.450 + exigência destacada em amarelo: *Ensino Médio Completo*. Copy: *“Não perca mais vagas de trabalho de carteira assinada.”*

#### Ad Set 1.2 — Cluster 2: Concursos Públicos, CNH e Segurança (Alavancagem)
- **Público**: Homens e Mulheres, 23 a 46 anos, Brasil.
- **Interesses / Sinais**: Concursos públicos, Gran Cursos, Estratégia Concursos, CNH / Detran, Vigilância Armada, Segurança Privada, Correios, Polícia Militar.
- **Exclusões**: Compradores últimos 180 dias.
- **Criativos Alocados**:
  - `VID_CON_01` (9:16): *“Concurso de nível médio pagando R$ 4.200 com inscrições abertas. Mas você precisa do certificado registrado no Diário Oficial.”*
  - `VID_CON_02` (9:16): *“Quer mudar a categoria da CNH para D ou E ou trabalhar em segurança armada? O pré-requisito é o certificado oficial.”*
  - `IMG_CON_01` (1:1): Comparativo: Edital Aberto vs. Certificado em Mãos. Headline: *“Garanta a sua posse no concurso público.”*

#### Ad Set 1.3 — Cluster 3: Superação & Orgulho Familiar (Emocional / Dignidade)
- **Público**: Homens e Mulheres, 32 a 58 anos, Brasil.
- **Interesses / Sinais**: Família, Educação de Adultos, Pais, Superação, Cursos técnicos.
- **Exclusões**: Compradores últimos 180 dias.
- **Criativos Alocados**:
  - `VID_ORG_01` (9:16): *“Você não parou de estudar porque quis. Você teve que colocar comida na mesa e criar seus filhos. Mas a sua história não acabou.”*
  - `VID_ORG_02` (9:16): *“O orgulho de pegar o seu diploma na mão e ser o maior exemplo para a sua família.”*
  - `IMG_ORG_01` (1:1): Foto autêntica e humanizada de um trabalhador maduro sorrindo com o certificado na mão.

#### Ad Set 1.4 — Advantage+ Audience / Broad (Qualificação pelo Criativo)
- **Público**: Aberto 22 a 55 anos, Brasil. Sem interesses segmentados.
- **Lógica**: O algoritmo do Meta utiliza o machine learning de criativo + sinais do Pixel/CAPI para encontrar os bolsões mais baratos de audiência em escala.
- **Criativos**: Os 3 melhores campeões (winners) dos Ad Sets 1.1, 1.2 e 1.3.

---

### CAMPANHA 02: `[SB]_CONV_META_REMARKETING_RESGATE_ABO`
* **Tipo de Orçamento**: ABO (Ad Set Budget Optimization) para garantir entrega em cada camada de público morno.
* **Conjuntos de Anúncios**:

#### Ad Set 2.1 — Visitantes de LP sem Lead (Últimos 14 dias)
- **Público**: `PageView` em `supletivo.net.br` menos quem iniciou Omnibar.
- **Ângulo**: Eliminação de Dúvidas de Credibilidade e Segurança Jurídica.
- **Criativo**: *“É oficial mesmo? Veja como o seu certificado sai publicado no Diário Oficial e tem amparo da LDB e autorização legal. Sem pegadinhas.”*

#### Ad Set 2.2 — Ghost Leads da Sofia Omnibar (Últimos 7 dias)
- **Público**: Dispararam evento `Lead` (Passo 1 do WhatsApp), mas não concluíram validação de CPF ou avanço para checkout.
- **Ângulo**: Assistência Humanizada e Condição Especial.
- **Criativo**: *“Vimos que você iniciou sua consulta mas não terminou. Ficou com dúvida sobre a bolsa de R$ 99/mês ou sobre o tempo de conclusão? Fale direto com a Sofia pelo WhatsApp.”*

#### Ad Set 2.3 — Abandonadores de Checkout & Carrinho (Últimos 3 dias)
- **Público**: Dispararam evento `InitiateCheckout` menos quem disparou `Purchase`.
- **Ângulo**: Urgência Real de Fechamento de Turma e Flexibilidade de Pagamento.
- **Criativo**: *“Sua vaga na turma expressa de homologação foi reservada. Garanta 12x de R$ 99 no cartão ou desconto especial no Pix antes do encerramento das vagas desta semana.”*

---

## 4. Matriz de Campanhas no Google Ads (Search & Performance)

### CAMPANHA G01: `[SB]_SEARCH_FUNDO_FUNIL_INTENCAO_ALTA`
* **Rede**: Apenas Rede de Pesquisa do Google (desativar parceiros de pesquisa e rede de display).
* **Estratégia de Lances**: Maximizar Cliques com CPC Limite de R$ 3,20 nos primeiros 7 dias -> Transição para Maximizar Conversões com Target CPA (tCPA) de R$ 135,00.
* **Grupos de Anúncios e Palavras-Chave**:

#### AdGroup 1: Supletivo Online & MEC (Alta Intenção Direta)
- `[supletivo online]`
- `[supletivo online rapido]`
- `"supletivo a distancia reconhecido pelo mec"`
- `"supletivo online confiavel"`
- `[supletivo rápido em 30 dias]`
- `[supletivo reconhecido pelo mec]`

#### AdGroup 2: Conclusão do Ensino Médio
- `[terminar ensino medio rapido]`
- `[concluir ensino medio pelo celular]`
- `"como terminar o ensino medio depois de adulto"`
- `"certificado ensino medio urgente"`
- `[supletivo para terminar ensino medio]`

#### AdGroup 3: EJA a Distância
- `[eja a distancia]`
- `[eja online reconhecido pelo mec]`
- `"eja rapido online"`
- `[concluir eja pelo celular]`

#### AdGroup 4: Ensino Fundamental
- `[supletivo ensino fundamental]`
- `"terminar ensino fundamental online"`
- `[eja ensino fundamental a distancia]`

### Lista de Palavras-Chave Negativas Obrigatórias (Negative Keywords List)
* **Gratuidade & Ilusão**: `gratis`, `gratuito`, `de graça`, `sem pagar`, `governamental`, `prefeitura gratis`, `pdf gratis`, `download de apostila`, `respostas das questoes`, `gabarito`.
* **Outros Exames / Não-Concorrentes**: `encceja inscricao`, `como fazer encceja`, `resultado encceja`, `enem inscricao`, `enade`, `faetec`.
* **Menores de Idade**: `menor de 15 anos`, `escola para criancas`, `creche`, `ensino fundamental 1 ao 5 ano`.
* **Incompatíveis**: `vagas de emprego rj`, `trabalhe conosco supletivo`.

---

### CAMPANHA G02: `[SB]_SEARCH_INTENCAO_PROFISSIONAL_CONCURSOS`
* **AdGroup 1**: Concursos Públicos
  - `"ensino medio para concurso publico"`
  - `"preciso de certificado de ensino medio para posse"`
  - `"supletivo rapido para concurso"`
* **AdGroup 2**: CNH e Carteira de Habilitação
  - `"escolaridade minima para cnh d"`
  - `"supletivo para tirar cnh de caminhao"`

---

### CAMPANHA G03: `[SB]_SEARCH_DEFESA_MARCA_INSTITUCIONAL`
* **Palavras-chave**: `[supletivo brasil]`, `[supletivo brasil online]`, `[supletivo net br]`, `"supletivo brasil é confiavel"`, `"supletivo brasil oficial"`.
* **Estratégia**: Maximizar Parcela de Impressões (Target Impression Share: 98% no topo absoluto da página). CPC controlado (R$ 0,25 a R$ 0,55).
* **Objetivo**: Proteger os cliques gerados pelo tráfego de Meta Ads e pelo trabalho dos Promotores, impedindo que concorrentes roubem o lead no momento da busca de validação.

### Assets e Extensões Mandatórias nos Anúncios de Busca:
1. **Sitelinks**:
   - *Certificado Reconhecido MEC* -> `/privacidade` ou seção de LDB.
   - *Condições e Parcelamento* -> `#preco` (12x de R$ 99).
   - *Consulta de Elegibilidade* -> Sofia Omnibar.
   - *Depoimentos de Alunos* -> Prova social real.
2. **Frases de Destaque**:
   - *Publicação em Diário Oficial*
   - *Estudo 100% pelo Celular*
   - *Sem Mensalidades Surpresa*
   - *Início Imediato da Turma*
3. **Snippets Estruturados**:
   - *Cursos: Ensino Médio, Ensino Fundamental, EJA Completo.*
4. **Extensão de Recurso de Chamada / WhatsApp**:
   - Direcionamento direto para a Sofia no WhatsApp.

---

## 5. Infraestrutura de Rastreamento Avançado (Pixel, CAPI e Safari ITP)

A integridade do rastreamento é a base para sustentar o CAC ≤ R$ 160,00. Identificamos pontos de melhoria na implementação atual e desenhamos a arquitetura definitiva:

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                    ARQUITETURA DE ATTRIBUTION & CAPI CLOUDFLARE                        │
├──────────────────────────┬─────────────────────────────┬────────────────────────────────┤
│ 1. CLIENT-SIDE           │ 2. CLOUDFLARE WORKER        │ 3. SERVER-SIDE CAPI / GTM      │
├──────────────────────────┼─────────────────────────────┼────────────────────────────────┤
│ • UTMs & Click IDs       │ • Extração de UTMs + GCLID  │ • Evento PageView server-side  │
│   (gclid, fbclid)        │   + FBCLID na borda         │ • Evento Lead (Passo 1 Sofia)  │
│ • First-Touch Cookie     │ • Emissão de Set-Cookie     │   com hash SHA256 de Tel/Email │
│   (supletivo.attr 90d)   │   (Max-Age 90 dias Lax)     │ • Evento Purchase (Webhook     │
│ • dataLayer.push()       │ • Mitigação Safari ITP      │   InfinitePay / Asaas)         │
│   em todos os CTAs       │   (First-Party Edge Cookie) │ • 100% deduplicação via        │
│                          │                             │   event_id compartilhado       │
└──────────────────────────┴─────────────────────────────┴────────────────────────────────┘
```

### Ajuste Crítico Identificado no Código do Edge Worker:
No arquivo `src/lib/attribution-cookies.ts`, a função `buildAttributionCookies(url)` atualmente só grava o cookie `supletivo.attr` quando `ref` está presente na URL (`if (ref)`).
* **Recomendação Técnica**: Atualizar a função para gravar `supletivo.attr` sempre que `utm_*`, `gclid` ou `fbclid` existirem, mesmo sem `ref` de promotor. Isso blinda a atribuição do tráfego pago direto contra o limite de 7 dias de cookies JS no Safari (ITP).

### Padrão Canônico de Taxonomia de UTMs:
```
https://supletivo.net.br/?utm_source=meta&utm_medium=cpc&utm_campaign=meta_cbo_aquisicao_eja_v1&utm_content=vid_emp01_vagas&utm_term=int_empregabilidade
https://supletivo.net.br/?utm_source=google&utm_medium=cpc&utm_campaign=gg_search_fundo_supletivo_v1&utm_content=anuncio_mec_rapido&utm_term=supletivo_online_mec
```

### Protocolo de Conversões CAPI (Meta) e Conversões Otimizadas (Google):
- Cada evento enviado pelo client e pelo server carrega um `event_id` único baseado em timestamp + telefone/hash.
- No evento `Lead` (Passo 1 Sofia Omnibar): Envio de `ph` (telefone com código de país `55` hasheado em SHA-256), `client_user_agent`, `client_ip_address`, `fbp` e `fbc`.
- No evento `Purchase` (Confirmação de pagamento InfinitePay/Asaas): Envio de `value`, `currency: "BRL"`, `em`, `ph`, `order_id` e atribuição original preservada.

---

## 6. Governança de Conteúdo Anti-Slop & Alinhamento com Bots Parceiros

Todo o ecossistema de criativos obedecerá rigorosamente às diretrizes do plano de growth:
- **Zero Construções de Negação Paralela**: Proibido usar *"Não é só um curso, é seu futuro"*. Usaremos afirmações operacionais: *"Você estuda no seu horário pelo celular e recebe o diploma válido pelo MEC publicado no Diário Oficial"*.
- **Alinhamento com Copywriter de Conversão**: Validação de todas as variações de títulos, descrições do Google Search e textos de feed/story antes da ativação.
- **Alinhamento com Editor**: Padronização dos primeiros 3 segundos dos vídeos para retenção de 50%+ em 3s, cortes rápidos, legendas nativas com fonte legível e áudio normalizado em -14 LUFS.
- **Alinhamento com Recuperação de Vendas**: Supressão imediata de alunos que geraram boleto/Pix nos públicos de topo e inclusão na régua de retargeting de alta urgência por 72 horas.

---

## 7. Próximos Passos Imediatos de Execução

1. **Validação do Edge Worker**: Solicitar ao time de infra/Cloudflare o ajuste em `attribution-cookies.ts` para persistência irrestrita de `gclid` e `fbclid`.
2. **Setup de Tags no GTM / Base.astro**: Inserção do container do GTM com gatilhos conectados aos eventos `cta_click` e `track()` já existentes no client.
3. **Produção dos Criativos Iniciais**: Encomendar ao **Editor** e ao **Copywriter** o primeiro lote de 9 criativos (3 por cluster) para o início da Fase 1.
4. **Submissão e Aquecimento**: Criação das campanhas estruturadas no Gerenciador de Anúncios e Google Ads para início do aprendizado de máquina.
