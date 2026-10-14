# Auditoria de pagamentos e plano de solução

Data: 13/10/2026. Escopo: InfinitePay para cartão, Asaas para Pix, ligação com matrícula/comissão, UI e UX dos pagamentos e financeiro administrativo.

**Resultado:** há caminhos confirmados no código que permitem pagamento na operadora sem aplicação correspondente no app. A integração atual não deve ser considerada concluída pelo sucesso de um pagamento isolado. Este documento propõe a correção; não registra sua implementação.

## 1. Evidência e limites da análise

Foram delegadas três frentes: contrato oficial InfinitePay, UI e UX. A análise de contrato terminou; as frentes UI/UX entregaram achados parciais antes de interrupção por limite de créditos. O agente principal conferiu os trechos apontados, cruzou a integração dos dois provedores e consolidou este plano.

Fontes: código atual, leitura somente consulta do banco em produção, documentação oficial e uma inspeção visual desktop da tela real de pagamento. Não foram emitidas novas cobranças, efetuados pagamentos, reprocessados eventos nem modificados usuários nesta auditoria. A análise mobile ainda é de código; exige execução visual na etapa de aceite. Não foi verificada a configuração de taxas/parcelas da conta InfinitePay no aplicativo da operadora.

As publicações anteriores foram conferidas pelos registros: backend `.110`, admin `.111` e app `.112`. O deploy dessas correções de navegação não resolveu os problemas financeiros encontrados aqui. Os 909 testes existentes do backend são evidência automatizada, e não comprovação destas jornadas em produção.

### Leitura de produção

Na consulta havia quatro leads, três pendentes e um pago; um checkout de negócio Asaas pago. Esse checkout possui confirmação, recibo e uma comissão, mas o usuário atualmente tem papéis administrativos/promotor e não possui matrícula nem aluno. O histórico da sessão inclui limpezas/recriações de canários; a consulta não determina a causa desta divergência.

Também existe uma intenção InfinitePay paga, emitida em 10/10, de 101 centavos com 107 centavos pagos, sem vínculo com checkout de negócio atual. Isso é compatível com o teste direto anterior relatado pelo usuário, mas precisa classificação explícita antes de qualquer recuperação. Não atribuir automaticamente esse recebimento a uma matrícula nova.

Contagens de eventos com `forwarded_ok=False` incluem testes, eventos incompletos e operações que podem não ser matrículas. Não representam, por si, alunos que pagaram e ficaram bloqueados. Além disso, o código grava `forwarded_ok=True` para eventos sem consumidor: nem esse indicador prova aplicação de negócio.

No Chrome, a sessão existente, ao abrir `/student/lead/payment`, exibiu “Sua proposta não carregou”, preços indisponíveis e ações de pagamento desabilitadas; continuou mostrando “LIBERAÇÃO IMEDIATA” e “pagamento em uma parcela” sem proposta disponível. A recuperação oferecida é recarregar. Esse caso deve distinguir ausência/permissão de papel, proposta inexistente e falha de rede; não justifica gerar cobrança automaticamente.

## 2. Contrato oficial: fatos e incertezas

O Checkout Integrado usa `POST /links`, `handle`, `items` com preços em centavos e `order_nsu`. A resposta de criação exemplifica `url`; não exigir `slug` nesse momento. [Central oficial InfinitePay](https://ajuda.infinitepay.io/pt-BR/articles/10766888-como-usar-o-checkout-integrado-da-infinitepay).

O retorno e o webhook fornecem referências de transação; `payment_check` exige `handle`, `order_nsu`, `transaction_nsu` e `slug`. O webhook usa `invoice_slug`. A documentação orienta reconhecimento HTTP 200, HTTP 400 para problemas/reenvio e resposta rápida. Não fornece garantia de idempotência de criação, consulta por pedido sem referências, retry de 500 ou parâmetros de juros/limite de parcelas. [Contrato oficial do Checkout](https://www.infinitepay.io/checkout-documentacao).

As opções comerciais variam entre produtos; a configuração efetiva do Checkout Integrado precisa ser conferida na conta, sem transportar regras do produto Site. [Repasse de taxas no Link](https://ajuda.infinitepay.io/pt-BR/articles/11731276-como-configurar-o-repasse-de-taxas-no-link-de-pagamento), [Configuração do Site](https://ajuda.infinitepay.io/pt-BR/articles/14497696-como-configurar-os-pagamentos-aceitos-em-meu-site).

No Asaas, pagamentos do QR estático geram cobrança e o `pixQrCodeId` identifica o QR original. Webhooks podem se repetir; a fila pode pausar após falhas consecutivas. Persistência, idempotência e recuperação local são necessárias. [QR estático](https://docs.asaas.com/docs/o-que-e-qr-code-estatico), [Webhooks](https://docs.asaas.com/docs/webhooks-2), [Fila pausada](https://docs.asaas.com/docs/fila-pausada).

**Não documentado não significa impossível.** Antes de implementar dependências de um recurso ausente destas fontes, obter confirmação específica da InfinitePay. Não inventar endpoint de cancelamento/estorno, assinatura, `max_installments` ou idempotência remota.

## 3. Falhas de coesão confirmadas

| Prioridade | Evidência do código | Consequência |
|---|---|---|
| P0 | `users/roles/lead/service.py:1056` cancela quando possível e apaga o checkout anterior; `:1072` não cancela o link InfinitePay; `:1306` procura somente o vínculo presente | Pagar link antigo pode não encontrar a matrícula. Mesmo selecionar novamente o mesmo meio substitui a linha. |
| P0 | `_fill_card`, `service.py:508`, chama criação sem identidade estável; vínculo só é salvo após resposta externa | Queda entre criação e persistência, ou repetição do builder, pode deixar intenção órfã e criar outra. |
| P0 | `infinitepay/webhooks.py:61` e `asaas/webhooks.py:144` marcam encaminhamento mesmo se nenhum hook consumiu | Evento reconhecido sem efeito no app fica representado como sucesso. |
| P0 | InfinitePay confirma o pagamento na integração antes do hook de negócio; não foi encontrado replay durável para essa integração | Exceção, referência ausente ou consulta temporariamente inconclusiva pode depender de outro callback externo para recuperar. |
| P1 | `infinitepay/webhooks.py:126` verifica apenas `paid_amount` quando presente, ignora `amount` e usa o esperado quando falta valor | Evidência monetária incompleta pode ser apresentada como valor confirmado. |
| P1 | `infinitepay/webhooks.py:101` aceita duplicado já pago sem confrontar transação/slug e encaminha recibo do novo payload | Recuperação pode usar dados não verificados do callback duplicado. |
| P1 | `infinitepay/webhooks.py:107` usa handle atual, apesar do handle de emissão estar no payload persistido | Mudar configuração da conta pode impedir a confirmação de pedido antigo. |
| P1 | `users/roles/lead/hooks.py:11` não transmite `amount_cents` à regra de negócio | A barreira monetária está apenas na integração; falta defesa e evidência na aplicação ao pedido. |

Existem proteções que devem permanecer: consulta out-of-band InfinitePay, QR Pix de uso único, casamento por `pixQrCodeId`, transação de banco para lead/matrícula/comissão e unicidade da comissão. O plano não substitui essas proteções por confirmação de navegador ou botão manual de “pago”.

## 4. UI e UX: o que corrigir

| Situação atual | Solução proposta |
|---|---|
| `PixCheckout.svelte:61` conserva tela pronta quando polling falha e continua afirmando “Radar Bancário Ativo” | Manter o código já recebido visível, marcar consulta indisponível, mostrar hora da última consulta e oferecer recuperação. Não confundir QR disponível com confirmação sendo consultada. |
| `PixCheckout.svelte:70` mostra “Copiado” mesmo se clipboard falha | Só anunciar sucesso após escrita concluída; na falha, selecionar o código e orientar cópia manual. |
| `PixCheckout.svelte:90` envia todo pagador de token público para matrícula | Mostrar confirmação/recibo público; continuar matrícula somente quando o servidor identifica a sessão do aluno responsável. Outra pessoa pode pagar para o aluno, sem ganhar acesso aos dados dele. |
| `StudentLockedPaywall.svelte:124` interpreta flag global/referrer/query como retorno do cartão e ignora restauração do checkout vigente | O servidor identifica pedido e tentativa; memória local pode ajudar a retomar a tela, mas nunca decidir provedor, confirmação ou vínculo. Limpar estado por usuário/tentativa. |
| Retorno InfinitePay apenas consulta `getLeadMe`; fechar a página depende do webhook para completar | Usar as referências recebidas para solicitar verificação ao backend autorizado. A conclusão precisa continuar no servidor mesmo sem navegador aberto. |
| Tela anuncia condições de parcelas sem o payload atual impor essas condições | Exibir proposta nominal do backend e condições efetivas do checkout/conta; separar total base, total pago, parcelas e acréscimos confirmados. O usuário já autorizou manter o repasse de taxas; não alterar essa configuração por inferência. |
| Dois itens do dock podem aparecer ativos; voltar depende de evento local e rota permanece checkout | Uma fase ativa, proveniente de estado/rota consistente. Voltar para revisar meio não emite cobrança. |
| Erros de papel/proposta, autenticação e conexão recebem recuperação genérica por reload | Usar ação específica: entrar novamente, abrir ambiente autorizado, retomar proposta ou tentar consulta. Recarregar não deve ser um ciclo sem saída. |
| `admin/FinanceView.svelte:80` ignora rejeições individuais e apresenta R$0/lista vazia | Cada saldo/resumo/lista tem carregamento, dado confirmado e erro próprios. Nunca substituir indisponibilidade por zero. |
| `admin/PricingView.svelte:617` chama rascunho de “Configuração Sincronizada” | Separar valor salvo, rascunho alterado, salvamento e erro; não usar fallback comercial inventado. |

Direção visual: resumo compacto da proposta com responsáveis e valor, uma ação principal, comprovante acessível, mensagens específicas e navegação previsível. Aplicar tokens canônicos, alvos de 48px, foco de teclado, `role=status`/`role=alert`, contraste e redução de movimento. A estética não pode anunciar conclusão ou atividade inexistente.

### Estados visíveis propostos

| Mensagem para o aluno | Evidência necessária | Ação |
|---|---|---|
| Escolha como pagar | Proposta existente e valores obtidos | Selecionar meio |
| Preparando cobrança | Tentativa local persistida, emissão pendente | Aguardar ou retomar consulta |
| Aguardando pagamento | Link/QR real e tentativa válida | Pagar, revisar proposta |
| Não conseguimos atualizar agora | Falha na consulta | Reconsultar; evitar pagar novamente |
| Pagamento recebido; finalizando matrícula | Provedor verificado, aplicação de negócio pendente | Acompanhar; não emitir segunda cobrança |
| Matrícula liberada | Aplicação concluída e destino autorizado | Documentos da matrícula |
| Pagamento precisa de conferência | Valor/referência divergente ou criação incerta | Atendimento com referência do caso |
| Estorno em análise | Registro efetivo de estorno/contestação | Revisão do admin e ações no parceiro |

Esses estados de pagamento não criam novos papéis de aluno. Lead continua lead até a aplicação de negócio concluir; os estados de pagamento explicam o processamento.

## 5. Plano final de implementação

### Entrega A — Preservar identidade e histórico das cobranças

Backend, antes de mudar a tela:

- Criar tentativas persistidas ligadas à proposta; manter checkout vigente e tentativas substituídas. Preservar token, provedor, conta emissora, identidade local, referências externas, valor contratado e evidência de pagamento.
- Persistir a relação lead → tentativa → intenção InfinitePay **antes** da chamada externa. Usar bloqueio curto no banco para reservar emissão, sem manter transação aberta durante rede.
- Clique repetido no mesmo meio retoma a tentativa válida. Trocar meio cria outra tentativa sem apagar a anterior. Não considerar link externo cancelado sem confirmação real.
- Resultado externo incerto recebe estado próprio. UUID estável local não prova idempotência remota: não repetir `POST /links` às cegas após timeout.
- Primeiro pagamento válido conclui a proposta uma única vez. Se outra tentativa também receber dinheiro, registrar recebimento adicional e encaminhar revisão/estorno; não criar outra comissão ou matrícula e não ignorar o dinheiro.
- Auditoria financeira deve sobreviver às limpezas de usuários de teste. Classificar canários diretos, pagamentos de matrícula e registros de usuário recriado antes de restaurar vínculos.

Aceite: todos os pagamentos de tentativa antiga encontram sua proposta, inclusive após troca e reinício; dois builders não criam duas intenções locais; nenhum histórico financeiro é apagado por troca de meio.

### Entrega B — Receber, verificar e aplicar com recuperação durável

- Persistir evento antes do reconhecimento HTTP. Criar fila de entrada no PostgreSQL principal e processamento no Django-Q existente, com leitura periódica de recuperação. Evitar instalar infraestrutura nova sem necessidade.
- Registrar recebimento, verificação do provedor, aplicação de negócio, erro, tentativas e próxima recuperação separadamente. `forwarded_ok` não representa todos esses resultados.
- Deduplicar pelo identificador disponível e pelas referências financeiras verificadas. Duplicado reaplica somente evidência persistida e não troca transação/comprovante por conteúdo público novo.
- Consulta InfinitePay usa conta da emissão. Validar campos, tipos, moeda/unidade, transação, pedido e valores; ausência/contradição financeira pede conferência, nunca valor pago inventado.
- Preservar aplicação atômica e idempotente de pagamento → matrícula → comissão. Reprocessador usa esse mesmo serviço e não confirma dinheiro por flag da UI.
- Recuperação de callback perdido usa referências do retorno, eventos recebidos e ferramentas reais do provedor. Se faltarem `transaction_nsu`/`slug` e não existir API documentada para localizar a transação, registrar o bloqueio e recorrer ao painel/operador; não prometer reconciliação impossível por código.
- Especificar a regra `amount`/`paid_amount` com a InfinitePay antes de codificar tolerância de taxas. Registrar valor base e acréscimo separadamente.
- Estorno InfinitePay: obter contrato de API se disponível; até lá, prever procedimento assistido no aplicativo da operadora, com registro e reversão idempotente. Não inventar webhook de refund.

Aceite: reinício após receber evento, interrupção após verificar provedor e falha durante matrícula convergem depois da recuperação; duplicados não duplicam efeitos; evento sem consumidor permanece identificado e recuperável.

### Entrega C — Um contrato de consulta para todo o app

- API autenticada devolve proposta, tentativa vigente, tentativas anteriores pertinentes, provedor/meio efetivos, valor contratado/pago, situação verificável, `last_checked_at`, recibo, motivo público e próxima ação permitida.
- Cartão/PIX, landing, app, hub, promotor e admin consultam os mesmos fatos. Flags de localStorage, URL e texto do botão não decidem pagamento.
- Endpoint público Pix conserva sua privacidade. A confirmação pública não expõe nome/CPF, credenciais, comissão ou documentos.
- Retorno externo identifica a tentativa e solicita verificação ao backend; o backend confronta autorização e referências. Não aceitar “success” na query como confirmação.
- Destino do aluno é resolvido pelo backend conforme papel/status atual. Prova continua condicionada aos dois meses desde confirmação de pagamento e aos documentos educacionais aprovados.

Aceite: fechar aba, perder sessão, retornar em outro aparelho ou reabrir WhatsApp não emite nova cobrança nem direciona uma sessão de outra pessoa à matrícula do pagador.

### Entrega D — Ajustar UI, UX e operação administrativa

- Implementar os estados da tabela, resumo de proposta, cópia honesta, retomada e comprovante. Remover promessas de tempo/parcelas sem evidência.
- Confirmar configuração da conta e checkout reais de cartão. Se o checkout oferecer outro meio, registrar o meio efetivamente utilizado; não chamar Pix de cartão no financeiro.
- Admin mostra divergência provedor × aplicação, falha de confirmação, tentativas substituídas, recebimento adicional e última recuperação. Pode solicitar nova verificação; não marcar “pago” sem evidência.
- Valores indisponíveis ficam indisponíveis. Draft comercial nunca aparece como salvo.
- Monitorar idade do pagamento confirmado sem matrícula, eventos sem vínculo, erros/retries, fila pausada Asaas e divergência de valor. Metas de prazo devem ser medidas nos canários e definidas antes do release, sem inventar SLA.

Aceite: erros de rede mostram estado correto; leitura do saldo falhando não produz R$0; usuário sabe se deve aguardar, reconsultar ou procurar atendimento, sem incentivo a pagar novamente.

### Entrega E — Provar o conjunto e publicar

Testes de domínio/contrato cobrem falhas deliberadas em ambiente controlado. Não confundir esses testes com o canário real. Depois, executar pela landing/app e registrar:

| Cenário | Resultado obrigatório |
|---|---|
| Pix de R$1,01 vinculado à proposta | Asaas, integração, app, matrícula, comissão de teste R$0,01, recibo e notificação concordam |
| Cartão de R$1,02 pela API utilizada | Referências reais, valor/parcelas/acréscimos observados, confirmação e efeitos concordam |
| Fechar a aba após pagar | Matrícula concluída pelo servidor; sessão posterior retoma estado correto |
| Callback atrasado/duplicado | Recuperação e somente um efeito financeiro/de negócio |
| Trocar meio e pagar link anterior | Histórico encontra o pagamento; segunda cobrança não gera efeitos duplicados |
| Falha após emissão e antes de resposta | Tentativa incerta é visível; repetição não cria cobrança cega |
| Falhar banco/rede/worker em cada fronteira | Recuperação preserva evidência, sem falso “confirmado”, “copiado” ou saldo zero |
| Pix aberto por outra pessoa/sem login | Pagamento permitido; documentos e sessão do aluno não expostos |
| Estorno/contestação | Pendentes cancelados, pagos compensados; matrícula externa submetida à revisão administrativa |
| Smartphone e desktop | Conteúdo/QR/CTA/dock sem corte, scroll/teclado/foco funcionam e movimento respeita preferência |

Não realizar todos os cenários pagos repetidamente por rotina: teste real por jornada e variação externa relevante; simular falhas em ambiente controlado. Cartão e pagamento no banco continuam sendo ações do titular. OTP pode ser conferido pelo GOWA autorizado; não solicitar códigos desnecessariamente.

Os pequenos valores são exclusivamente de canário isolado. Tabela comercial e propostas já emitidas permanecem preservadas. Depois de conferir os pagamentos, testar bônus/repasse com os valores canário já autorizados e sem promover saldo comercial ao canário.

Release: artefato identificado, testes necessários, publicação backend compatível antes do app/admin, smoke autenticado real, observação das filas e rollback documentado. Migrações preservam o histórico; não remover tabela/coluna financeira na reversão de código. Cada entrega registra versão no oráculo global, commit, hashes, imagem/Worker, evidências e limitações.

**Critério para declarar esta jornada disponível:** a mesma tentativa deve ser rastreável do link até a confirmação externa, aplicação da matrícula, comissão, comprovante e notificação; deve recuperar as falhas previstas sem exigir outra cobrança. Os dois provedores precisam satisfazer esse critério separadamente.

## Sequência proposta

A → B → C → D → E. Há uma decisão externa a conferir durante A/B: contrato real de repetição/criação incerta, taxas/parcelas e possibilidade de localizar/estornar venda na InfinitePay. A conferência não bloqueia a correção de histórico, recebimento durável e erros da UI.

Esta auditoria não corrige automaticamente as divergências existentes, nem homologa qualquer pagamento. As leituras e reproduções locais identificam os problemas; a matriz define a evidência ainda necessária.
