# Encerramento técnico das pendências de identidade

Escopo pedido pelo proprietário: recuperação de OCR intermitente, motivos de outra etapa no promotor, orientação incorreta após revisão e mensagens de PDF protegido/excessivo. Correções publicadas na `.92` e preservadas pelo backend `.93`, publicado por outra execução durante o reteste. App sincronizado à versão global `.93`, com o mesmo código funcional testado. Esta rodada encerra esses defeitos técnicos, sem declarar homologação do proprietário ou conclusão da plataforma inteira.

## Correções e limites de execução

- Cada requisição Cloudflare recebe seu próprio timeout HTTP, mesmo quando reutiliza o pool. Um prazo de parede cancela a espera inteira. A telemetria distingue read/connect/write/pool/total timeout, falha de transporte e HTTP sem registrar conteúdo privado da exceção.
- A leitura de identidade tem orçamento compartilhado de 120 s entre faces, estruturação e credenciais. Cada OCR Scout tem no máximo 60 s e uma recuperação para falhas transitórias: duas tentativas totais por fonte, sempre limitadas pelo orçamento restante. HTTP/input não recuperável, texto vazio ou truncado não são repetidos nem considerados identidade conferida. Esgotamento continua em revisão, sem inventar dados ou aprovar.
- O promotor mostra blocos pertinentes à etapa e ao tipo atual; revisão/rejeição global mantém os motivos identificados por título. Uma CNH em revisão orienta aguardar o polo, sem afirmar que OCR continua executando.
- O decoder distingue senha, páginas excessivas, PDF vazio e falha de renderização. Apenas códigos conhecidos viram mensagens de arquivo na UI; prosa livre da IA não substitui essas instruções. Aluno e promotor compartilham essas mensagens.

Uma recuperação limitada trata a falha transitória; não garante disponibilidade permanente da Cloudflare. As duas falhas reais `.90/.91` permanecem no histórico. Não foram apagadas para declarar sucesso.

## Evidência separada por natureza

150 testes locais de backend passaram em 7,86 s, 30 de frontend passaram; Astro checou 118 arquivos, zero erros/avisos; builds `.92` e sincronização `.93` passaram. Os testes locais exercitam falhas controladas, orçamento, cancelamento, não preenchimento e preservação de fontes; não equivalem a acurácia universal de OCR.

O probe de recuperação em produção encurtou deliberadamente o prazo da primeira **requisição real** à Cloudflare, em processo isolado. Ela falhou com `total_timeout`; a tentativa seguinte leu o documento original. Nenhuma resposta foi fabricada, nenhum segredo/configuração de produção foi alterado e não houve escrita em cadastro. A auditoria de IA registrou erro em 218 ms e sucesso em 26049 ms. Duas tentativas Scout, resultado em 32823 ms, nome/CPF/nascimento conferidos e registro/categoria correspondentes ao original. Trata-se de falha induzida de rede, não de indisponibilidade natural nem de jornada pela UI.

Sete casos de UI real passaram: estado controlado de revisão com documento original (sem fabricar OCR), PDF protegido e PDF com três páginas em cada papel, RG original inteiro e CNH original inteira. O estado de revisão usou preparação controlada no banco para conferir o texto; os uploads e os decoders foram reais. O estado antigo de erro de endereço continuou armazenado e foi ocultado durante identidade, reaparecendo com título próprio apenas na sua etapa.

| Jornada real após a correção | Task | Resultado |
| --- | --- | --- |
| CNH original, candidato | `c5f4ac1d1c39483fb7e93673660a5037` | Aprovada; `2026-10-12T02:25:41.975374Z`–`02:26:10.472700Z`; nome/CPF/nascimento match; registro/categoria/validade comparados ao original tanto na extração quanto no banco; RENACH incerto nulo |
| RG JPG original inteiro, aluno | `91dbc7ca941e45f3b17e0ece32cca20f` | Aprovado; `02:27:29.271995Z`–`02:27:39.614143Z`; uma fonte full, nome/CPF/nascimento match, número persistido igual à transcrição |

GOWA confirmou os avisos enviados: CNH `3EB0D24067554301DC44CA`, `02:26:15Z`; RG `3EB0664CBDE3635A504E6C`, `02:27:43Z`. Não há valores pessoais ou conteúdo de documento neste relatório. A exibição automática da próxima etapa não constitui envio/teste de endereço.

## Publicação, concorrência e rollback

Nossa publicação backend `.92`: release `identity-pending-20261012-v92`, artifact `f50363e33914553e763ac60e28ba2decfe90494a4e1b6ff2cad190f62df17c83`, imagem `sha256:5b59b759f278c254736c3d2e81dcf84284628e5dc50170a55b5c53c13ce1c0ae`, build `02:17:43.169122Z`, promoção `02:18:22.819618Z`. Preflight sem migrações. App `.92`: Worker `ff1d3764-1b00-42c9-b22a-634265bc0f4a`.

Outra execução publicou backend `.93`: artifact `997020e7c464b7d13902053fd390d818693a1597cae8939dced11e9ca40a2c6f`, build `02:19:46.321550Z`. Os hashes dos cinco arquivos da nossa entrega foram conferidos dentro da imagem ativa e todos coincidiam com os testados: `api/health/router.py`, `api/schemas/documents.py`, `core/pdf.py`, `integrations/ai/cloudflare.py`, `integrations/ai/service.py`. Os canários finais ocorreram nessa imagem; sua saúde pública retornou 200, db=true, migrações0. Não foi sobrescrita a publicação concorrente.

App sincronizado à versão global `.93`: Worker `46ce4e63-9f15-482e-b0ed-f4472f2bc8b5`, registro do módulo no oráculo `02:29:30.809Z`. A sincronização alterou somente a versão do pacote, com novo build/deploy; o código funcional permaneceu o que passou nos testes e na UI.

Rollback do app para a versão publicada anteriormente `.91`: Worker `aaab7a43-602a-41da-870f-4175d2310301`; `.92` também está disponível como publicação intermediária. O controller da nossa `.92` pode restaurar a base `.91` **apenas quando a imagem ativa ainda for a própria `.92`**, usando `/opt/v7m-platform/releases/identity-pending-20261012-v92/release.py rollback --expected-artifact f50363e33914553e763ac60e28ba2decfe90494a4e1b6ff2cad190f62df17c83`. A produção já avançou à `.93`: consultar o manifesto/controller da imagem ativa e conferir seu estado antes de rollback, para preservar mudanças da outra execução. Rollback de código não restaura banco.

## Limpeza e escopo preservado

Candidato/papel/usuário de estacionamento temporários foram encerrados; promotor histórico suspenso restaurado, tokens antigos invalidados e papéis originais admin/enrollment/staff preservados. Aluno pago, RG/CNH aprovados, proposta congelada, comissões pendentes/pagas e padrões de hub/promotor foram conferidos. Preços e regras comerciais permaneceram inalterados. Navegador devolvido ao RG aprovado após login via OTP lido pelo GOWA.

[Evidência estruturada](identity-pending-v92-evidence.json) · [Sete casos de UI](identity-pending-ui-v92.json) · [Histórico completo anterior](identity-retest-2026-10-11.md). Os arquivos locais e as mudanças de código estão disponíveis para revisão; não foram apresentados como commit publicado nesta rodada. Endereço, selfie ao vivo, contrato, ativação integral e jornadas financeiras não foram incluídos neste encerramento de identidade.

Issues técnicas encerradas como concluídas a pedido do proprietário: [backend #22](https://github.com/maestri33/backend.supletivo.net.br/issues/22#issuecomment-6116709720) e [app #17](https://github.com/maestri33/app.supletivo.net.br/issues/17#issuecomment-6116710361). Comentários contêm escopo, correções, evidências e limites; fechar a issue não é homologar a plataforma em nome do proprietário.
