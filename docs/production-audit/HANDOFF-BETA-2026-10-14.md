# Handoff — lançamento beta do Supletivo

Data: 14/10/2026, America/Sao_Paulo. Documento de orientação, não certificado de prontidão. Pedido do proprietário: ambientar o próximo agente sem inventar fatos e concluir o necessário para operação real. Somente o proprietário homologa a entrega.

## 1. Comece aqui: como recuperar a realidade

1. Leia `C:/rep/supletivo.net.br/AGENTS.md`, `DESIGN.md` e instruções específicas dos repositórios envolvidos. Regras de negócio mais recentes do usuário prevalecem sobre documentos antigos. Bancos principais permanecem Azure; D1 é para borda. Não interpretar “Cloudflare-first” como autorização para migrar PostgreSQL.
2. Antes de editar, execute `git status --short`, `git log -5 --oneline` e revise os diffs de cada repositório necessário. Alterações existentes não são descartáveis nem automaticamente desta execução. Não use reset/clean/stash amplo e não publique o working tree inteiro sem revisão.
3. Identifique outros agentes/processos e a responsabilidade sobre arquivos/deploys. O usuário informou anteriormente que Antigravity parou; isso é histórico, não prova de exclusividade atual. Havendo evidência de concorrência, coordene. Pode delegar auditorias independentes, com escopo claro; um responsável integra e publica.
4. Leia este handoff e os relatórios vinculados como pistas. Confira afirmações em código, banco somente leitura, configuração efetiva, API e navegador. Uma issue aberta pode já ter correção; uma issue fechada não comprova a produção atual.
5. Consulte o oráculo `https://version.v7m.live/api/version`, o health `https://backend.supletivo.net.br/api/v1/health/healthz`, versões ativas dos Workers, imagem dos containers e commits. A lista `apps` do oráculo não prova o código servido por cada app.
6. Use o navegador para reproduzir o fluxo visível. Leia a documentação das ferramentas CUA antes de operar. OTP pode ser lido pelo MCP GOWA autorizado: descubra suas ferramentas e leia `C:/Users/maestri33/.agents/skills/whatsapp-mcp/SKILL.md`. Não peça ao usuário um código que está disponível no canal autorizado.
7. Consulte documentação oficial atual antes de depender de comportamento de Asaas, InfinitePay, Cloudflare ou bibliotecas. Não invente endpoints, assinaturas, parâmetros, cancelamentos, idempotência remota ou garantias de entrega.

### Disciplina de evidência

Para cada conclusão registre: observado agora / histórico / inferido / não verificado. Inclua horário, versão/artefato, cenário, resultado esperado e obtido. Não confunda build, suíte verde, HTTP 200, webhook recebido ou container saudável com fluxo concluído. Nunca declare aprovação documental ou pagamento com base em flags alteradas manualmente.

Não exponha secrets, OTP, documentos, CPF, dados de terceiros ou credenciais do parceiro em logs públicos, commits e issues. A chave de produção enviada no histórico da conversa não deve ser copiada: verificar rotação e usar configuração protegida. Não solicitar credenciais novamente se a configuração autorizada já permite operar.

## 2. Estado observado nesta preparação

- Backend público respondeu `0.0.0-sandbox.119`, DB acessível, zero migrações pendentes; artefato `0e6ced6c56dc424531aa2a618b33413f00c8568c404820a4b99dd4b61508697c`.
- Container web observado: imagem `sha256:059f28fb487c2d202685f30b006bd26aa914f7cad1c8649a53e619b0f3a06f9e`.
- Consulta às configurações Django efetivas dentro do container: `APP_ENV=prod`, `TEST_MODE=false`, `TEST_EXTERNAL_ADAPTERS=false`, `ASAAS_BASE_URL=https://api.asaas.com`, `BIOMETRIC_ENABLED=true`. Não inferir configuração apenas de `docker inspect`: valores podem vir de arquivo/settings.
- Oráculo respondeu `.118`, com último módulo app. Há divergência de registro em relação ao backend `.119`; reconciliar antes da release beta.
- HEAD local backend observado: `c6acf4c`, entrega `.119` de TTS ElevenLabs; anterior `62e4da1` também alterou TTS. Isso exige conferir o escopo/configuração efetiva frente à preferência do usuário por IA Cloudflare; não desfazer automaticamente trabalho recente.
- Há numerosas alterações financeiras NÃO COMMITADAS e três novas migrações no backend. Incluem `users/roles/lead/payments.py`, `integrations/bank/recovery.py`, histórico de tentativas, webhooks dos dois provedores e `core/management/commands/payment_schedules.py`. Revisar e testar o que já existe antes de reimplementar. Não presumir que está publicado ou completo.
- O último relatório de navegação registra backend `.113`, app `.112`, admin `.114` e 910 testes backend, 36 app, 12 admin. Esses números pertencem àquela entrega; não descrevem automaticamente o working tree atual.
- Na consulta anterior não havia Student/Enrollment, apesar de fonte histórica paga. O proprietário tinha promotor/admin; histórico revogado não deve ressuscitar aba Aluno. Reconsultar agora. Não recriar matrícula a partir de pagamento antigo sem classificar vínculo/histórico.
- Produção já movimentou dinheiro real. Sair do rótulo `sandbox` não é trocar o endpoint Asaas de teste para produção.

## 3. Mapa inicial de repositórios e infraestrutura

| Diretório em C:/rep | Responsabilidade a conferir |
|---|---|
| supletivo.net.br | Landing do aluno; início real do canário |
| promotor.supletivo.net.br | Captação do promotor |
| app.supletivo.net.br | Aluno/promotor/coordenador, estados e docks |
| admin.supletivo.net.br | Frontend administrativo separado |
| backend.supletivo.net.br | Regras, PostgreSQL, pagamentos, filas, integrações |
| notify.supletivo.net.br | Entrega de notificações e integração WhatsApp |
| version.v7m.live | Oráculo global de versão |
| os.v7m.live | Lógica abandonada pelo usuário; fora do lançamento |

Azure observado: `azureuser@20.127.0.185`; Compose `/opt/v7m-platform/docker-compose.yml`; containers `v7m-backend-web`, `v7m-backend-qcluster`, serviço biométrico privado. Conferir inventário atual antes de usar. Frontends/borda na Cloudflare; PostgreSQL principal no Azure. Não contratar recursos adicionais silenciosamente. Planos informados pelo usuário: Workers Paid, R2 Paid, Images Stream Basic e Zero Trust Free; confirmar limites quando necessário.

Completar inventário por serviço: domínio, Worker/container, imagem/commit, banco, storage, fila/consumidor, webhook, nomes dos secrets (nunca valores), health, alertas, deploy e rollback. Links Azure/Cloudflare no admin não equivalem a inventário integrado.

## 4. Regras de negócio já decididas — não perguntar novamente

- Preços e dados exibidos vêm do backend. Sem indicação: Pix R$1.615 ou 12×R$159,90; com indicação: Pix R$999 ou 12×R$99. Sem referência, atribuir promotor padrão configurável no admin, sem confundir atribuição padrão com direito ao desconto. Alterações globais só valem para novas propostas; preservar propostas/cobranças emitidas.
- Cartão: InfinitePay. Pix, taxas e repasses: Asaas. O usuário aceitou prosseguir com a configuração encontrada no checkout; conferir valores/parcelas/acréscimos efetivos e não prometer taxas absorvidas sem prova.
- Lead vira matrícula ao pagar. Comissão do promotor R$100 por matrícula paga; bônus R$500 UMA vez ao atingir cinco no ciclo sexta 18h → sexta 18h, America/Sao_Paulo.
- Promotor começa a indicar imediatamente como candidato. Entrada gratuita. Ativação automática após cadastro, documentos e identidade aprovados. Saldo do candidato acumula; se ativar após fechamento, recebe no próximo. Treinamento/LMS fora desta versão.
- Estorno/chargeback: cancelar comissões/bônus pendentes afetados e compensar valores já pagos nos próximos repasses. Matrícula externa passa por revisão do admin; coordenador executa decisão no parceiro.
- Coordenador é promotor. Admin cria polo e seleciona/altera seu coordenador. Coordenador matricula no parceiro, informa Pix/QR, paga primeira taxa e agenda segunda pelo app/Asaas, registra acesso externo. Parceiro informado: `https://cbi.sistemasiga.net/login`.
- Prova presencial só pode ser agendada após DOIS meses desde pagamento e com documentos educacionais aprovados. Não converter silenciosamente dois meses em 60 dias; conferir implementação e tornar explícita qualquer ambiguidade residual.
- Documentos educacionais são pós-matrícula; sua ausência bloqueia prova, não o início do estudo por si só. Coordenador registra resultado/reagendamento e documentos emitidos pelo parceiro.
- Aluno vira veterano quando coordenador anexa diploma, novo histórico e foto da entrega física. Esse evento gera R$50 ao coordenador, pagos no fechamento semanal.
- Nossa plataforma não contém disciplinas/LMS. Acesso mostra parceiro, credenciais e situação real das duas taxas. Financeiro mostra pagamento efetivo, datas e recibos.
- Aluno: identidade somente RG; promotor: RG ou CNH. Um único espaço inicial de envio aceita foto/JPG/PNG/PDF. Classificar documento/não documento e frente/verso/ambos; pedir apenas lado ausente. Backend faz análise/extração assíncrona, compara nome com tolerância a sobrenomes, CPF quando presente e nascimento, e popula dados após verificação.
- Selfie é captura ao vivo, não upload de foto antiga de Downloads. Não relaxar biometria para aprovar canário.
- Escolaridade do aluno no máximo 3º ano do ensino médio; promotor pode ter superior completo. Estados e cidades por API; declaração final explícita de responsabilidade e uso dos dados para matrícula externa.
- Navegação administrativa: Alunos, Promotores, Polos e Administrador, com dock contextual. Nada de Processos/Bancas/Disciplinas inventados. Promotor tem documentos; admin gerencia questões gerais.

## 5. Canários e limites de atuação

Última definição do usuário: Victor como aluno criado pela landing, Diandra como promotora padrão e coordenadora do polo padrão. Isso é objetivo do canário, não afirmação do estado atual. Os dados autorizados estão na conversa e no cadastro; não transcrevê-los neste documento público. Há outros leads reais: não alterar terceiros.

Valores autorizados para testes isolados: Pix R$1,01; cartão R$1,02; comissão promotor R$0,01; bônus R$0,10; comissão polo R$0,05. Não colocar centavos na tabela global. Não apagar fontes financeiras para recriar usuários: preservar tentativas, pagamentos, recibos, auditoria e reversões. Preferir retomada/classificação do existente a nova cobrança desnecessária.

Documentos autorizados ficam em Downloads; identificar titular antes de usar. Caminho de comprovante fornecido consta na conversa. Não fabricar/alterar documentos ou resultados. Selfie e pagamento pelo banco/cartão exigem ação do titular. OTP via GOWA autorizado; verificar também notificações efetivamente enviadas, links e ausência de placeholders.

## 6. Trabalho necessário, em ordem

### A. Consolidar pagamentos e contabilidade — bloqueio de lançamento

Ler `payment-cohesion-plan-2026-10-13.md`, mas confrontar com os diffs atuais. Revisar implementação existente de tentativas persistentes, preservação de links anteriores, estado incerto de emissão, validação pelo provedor, inbox/retries e aplicação atômica/idempotente. Revisar migrações antes de executá-las.

Corrigir/verificar recebimento → ledger com bruto/líquido/taxas e recibo rastreável. `forwarded_ok` não comprova matrícula nem receita. Pagamento duplicado deve ter destino auditável, não ser ignorado. Não reemitir InfinitePay às cegas após timeout. Não usar retorno do navegador como prova de pagamento.

Aceite: Pix e cartão reais vinculados à proposta; app, provedor, matrícula, comissão, recibo e notificação concordam. Falha/retry/duplicado não duplicam efeitos. Trocar meio não perde vínculo de link anterior. Conciliação identifica diferenças e não inventa valor faltante.

### B. Jornada completa de aluno e promotor

Executar landing → proposta → pagamento → matrícula → RG/CNH → endereço → escolaridade → selfie/contrato → aprovação. Testar erros relevantes e caminho feliz, incluindo RG único com dois lados, lados separados, formato inválido, CPF divergente e recuperação após reload. Conferir fila/resultado/backend, não só toast.

Biometria: comprovar positivo e negativo reais, licença adequada dos pesos e limites de prova de vida. Conferir contrato de produção sem placeholder. Se o serviço falhar, UI precisa explicar revisão/retentativa; não aprovar silenciosamente.

### C. Polo e aluno ativo

Com matrícula real, testar pagamento/agendamento das taxas, recuperação de falha, registro de credenciais e acesso ao parceiro. Não pagar destinatário ou taxa inventados para completar tabela de testes. Testar autorização por polo: um coordenador não pode acessar rede alheia.

Comprovar bloqueios de prova e transição para veterano sem adulterar datas de pagamento em produção. Regras temporais e documentos finais podem ser exercitados em ambiente controlado; declarar esse limite e estabelecer acompanhamento da jornada real, sem fabricar diploma ou entrega.

### D. Comissões e reversões

Conferir cinco matrículas qualificadas, bônus único/ciclo, fuso/limites, candidato acumulando e ativo recebendo no ciclo seguinte. Coordenador recebe uma vez na entrega. Testar concorrência/reexecução e reversões. Repasse real canário deve estar vinculado à comissão; transferir centavos diretamente não prova o fechamento semanal.

### E. UI, acesso e operação

Testar celular/desktop: câmera/permissões, scroll, teclado, dock e ações por status. Pix público sem sessão, outra conta autenticada, token inválido e cobrança paga. Nenhuma falha deve mostrar saldo zero, copiado, salvo ou confirmado fictícios. Conferir permissões e acesso protegido a documentos/credenciais.

Conferir alertas reais de exceção, fila parada, webhook com erro e pagamento confirmado sem aplicação. Verificar configuração efetiva antes de afirmar que Sentry está ausente. Definir responsável pela operação e recuperação. Para beta com dados de clientes, comprovar backup/restauração apropriados; isso não exige backup desnecessário a cada leitura/teste.

## 7. Regra de release e decisão beta

1. Escopo e alterações revisados, testes relevantes e suíte backend inteira após ajustes, builds identificados.
2. Inventário de configuração/migração e rollback concreto compatível com o schema. Rollback de imagem não desfaz pagamentos nem migrações.
3. Registrar commit e incremento global conforme regras; reconciliar `.118`/`.119` antes de escolher próxima versão. Não usar número fixo deste arquivo no futuro. A promoção beta é decisão do proprietário.
4. Publicar somente artefato revisado; preservar secrets/bindings. Smoke na URL pública e interfaces autenticadas, versão conferida no runtime.
5. Atualizar issues/evidências com o que passou, falhou e não foi exercitado. Não encerrar pelo build.
6. Liberar beta fechado com grupo acompanhado quando bloqueios financeiros, identidade e jornada inicial estiverem resolvidos e o proprietário homologar. Jornada futura de prova/diploma precisa regras testadas e operação preparada, sem alegar que aconteceu ao vivo antes de ocorrer.

Fora do caminho crítico: LMS, automação da matrícula externa, novas vozes, integração completa de gerenciamento Azure/Cloudflare e refatorações cosméticas de rotas. Não abrir frentes novas para adiar o fechamento.

## 8. Referências e retomada objetiva

- `docs/production-audit/navigation-production-evidence-2026-10-13.md`: entrega anterior, limites e rollback daquela versão.
- `docs/production-audit/payment-cohesion-plan-2026-10-13.md`: diagnóstico financeiro; confrontar com alterações atuais.
- Backend issues: [18](https://github.com/maestri33/backend.supletivo.net.br/issues/18), [20](https://github.com/maestri33/backend.supletivo.net.br/issues/20), [21](https://github.com/maestri33/backend.supletivo.net.br/issues/21), [25](https://github.com/maestri33/backend.supletivo.net.br/issues/25).
- App: [14](https://github.com/maestri33/app.supletivo.net.br/issues/14), [16](https://github.com/maestri33/app.supletivo.net.br/issues/16). Admin: [3](https://github.com/maestri33/admin.supletivo.net.br/issues/3).
- Scripts de release backend: `deploy/release/prepare_backend_overlay.py`, `backend_overlay_remote.py`; revisar antes de reutilizar, não promover stage antigo sobre runtime novo.

Primeira entrega do próximo agente: mapa curto do estado atual + revisão dos diffs financeiros existentes + lista priorizada de lacunas confirmadas, seguida da execução da frente A. Perguntar apenas o que não foi decidido e realmente impede a próxima ação. Não reiniciar entrevistas sobre toda a plataforma, não prometer garantia absoluta e não entrar em ciclo infinito de auditoria sem correção e evidência.

Este handoff foi criado localmente; não implica commit, push, deploy, alteração de preços ou promoção para beta.
