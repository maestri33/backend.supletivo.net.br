# Endereço: entrega técnica e evidência de produção — sandbox.94

Data: 2026-10-12 (UTC). Homologação do produto pertence ao usuário.

## Comportamento entregue

Aluno e candidato a promotor usam a mesma validação de comprovante. O upload inicia uma geração identificada por `analysis_started_at`. A conclusão do OCR verifica novamente a fonte, a geração e o parecer vigente sob bloqueio transacional. Resultado de arquivo substituído, decisão anterior ou declaração de vínculo de outro arquivo é descartado. Reenvio limpa parecer, data e vínculo anteriores.

O `/me` e o GET isolado expõem `poll_after_ms`, `expires_at` e o início da análise. Pendência vencida vira revisão pela equipe. Visão, OCR e extração têm orçamento limitado: até 180 segundos, reduzido conforme o TTL, com tempo reservado para o JSON. A recuperação do OCR usa o cliente Cloudflare existente. As opções novas são restritas ao comprovante; outros documentos mantêm os padrões anteriores.

O aluno retoma o acompanhamento depois de recarregar a página. Recebimento, análise automática, vínculo, rejeição e revisão pelo polo têm mensagens distintas. Resultado de uma consulta iniciada antes de um novo envio não desfaz o recebimento novo. O promotor também descarta consultas antigas e usa o prazo fornecido pelo comprovante.

Triagem inconclusiva não conta como documento identificado. PDFs com senha, páginas excessivas ou arquivo inválido recebem orientação específica. Foram retiradas duas afirmações sem comprovação: criptografia de ponta a ponta nessa tela e referência genérica a uma portaria MEC/EJA no seletor de vínculo.

## Execução real

Foram utilizados o cadastro autorizado do aluno e um candidato temporário no mesmo usuário, preservando o promotor histórico suspenso. A identificação do candidato foi percorrida pelo app com RG real antes do endereço. O candidato não foi ativado; chave Pix, consentimento e selfie não foram enviados nesta rodada.

Uma fatura original indicada pelo usuário foi enviada como PDF no aluno, como PNG no promotor e como JPEG no aluno. As imagens são renderizações fiéis da página original, sem alteração de dados. Em todas as três execuções, o banco registrou `approved`; logradouro, número, bairro, cidade, UF e CEP conferiram com o original. A matrícula passou para `education`, e o promotor exibiu a etapa de dados de recebimento de comissões.

| Origem | Tarefa concluída | Início da geração | Parecer gravado |
| --- | --- | --- | --- |
| Aluno — PDF | `e311733efe534aacb89dde2eb4542564` | 03:12:44.543260Z | 03:13:09.419670Z |
| Promotor — PNG | `466235cac4d5492c8cb2558cafdcfcf7` | 03:23:25.347723Z | 03:23:54.845035Z |
| Aluno — JPEG | `37456a0e1ef342058386d547d3661c6e` | 03:26:45.012557Z | 03:27:14.873309Z |

No JPEG, a tela foi recarregada durante o OCR: mostrou o recebimento novamente e chegou à aprovação pelo acompanhamento automático, sem novo upload ou consulta manual.

Os nove erros exercitados em cada papel foram arquivo vazio, formato incompatível, tamanho excessivo, PDF com senha, PDF com três páginas, PDF corrompido, imagem corrompida, imagem sem documento e RG enviado no lugar do comprovante. Foram 23 observações de UI com resultado esperado: 18 rejeições, três aprovações, recebimento pendente e retomada após reload. Evidência: [address-v94-ui-evidence.json](address-v94-ui-evidence.json).

Os registros de visão/OCR/JSON das três aprovações apontam exclusivamente Cloudflare. O GOWA confirmou a entrega do OTP utilizado para o candidato e a aprovação da identificação. O fluxo atual de endereço exibe aprovação pelo `/me`; não emite notificação própria de aprovação. A correção do evento e da URL em rejeições de candidato está no código, mas não foi exercitada com uma rejeição assíncrona real nesta rodada: os arquivos negativos foram barrados pela triagem anterior ao upload de negócio.

## Regressão e release

- Sete falhas de concorrência/prazo foram reproduzidas antes da correção. A suíte nova contém nove casos, incluindo edição de endereço durante OCR e orçamento das chamadas.
- Bateria ampliada: **138 testes de backend**, **33 de frontend**; Astro Check: **119 arquivos, zero erros/avisos**. Esses testes usam substitutos locais de integrações e são evidência de regressão, não canários reais.
- Build Astro concluído. Backend preflight sem migrações pendentes; nenhuma migração aplicada.
- Backend: `address-recovery-20261012-v94`, imagem `sha256:b922b5780c3ff38eb952a1e01247ef926e0e44a2bf1d08693dff972b53a624b8`, artefato `52c7bd43166f07e1326715639a11f6c1d22d17943f397c10828a0797eee1b986`.
- Construção: 03:08:12.523563Z; promoção: 03:08:51.790187Z. Health indicou banco acessível e zero migrações pendentes.
- Worker do app: `baf785a0-af70-4c07-a31b-453426676a7a`; bindings existentes preservados. Registro no oráculo: 03:09:18.033Z.
- Overlay limitado a sete arquivos, com imagem ativa `.93` como base. Os seis arquivos de negócio foram comparados com a produção antes do overlay; diferenças da base local eram apenas finais de linha. Os cinco arquivos da correção anterior de identidade foram conferidos após a entrega e preservados.
- A origem do backend contém alterações locais (`source_dirty=true`); o SHA do artefato e os hashes por arquivo identificam a entrega. Não foi criado commit, PR ou push desta rodada.

## Limpeza e preservação

O candidato temporário foi removido, seu papel revogado e o promotor histórico restaurado. O usuário aluno, sua matrícula e o comprovante aprovado permaneceram. A conferência final preservou pagamento, valores congelados da proposta, comissão canário pendente, repasse anterior, preços comerciais e Diandra como coordenadora/promotora padrão.

Documentos e screenshots com dados pessoais estão em `.release-secrets/address-retest-20261012`; não foram publicados no GitHub. Há backup privado do comprovante, endereço e matrícula anteriores em `/opt/v7m-platform/private-canaries/address-retest-20261012-backup`.

## Rollback de código

Antes de agir, conferir a imagem/Worker ativos para não desfazer uma entrega concorrente. O controlador recusa rollback se o artefato `.94` já tiver sido substituído.

Backend, no host Azure:

```sh
sudo -n python3 /opt/v7m-platform/releases/address-recovery-20261012-v94/release.py rollback --expected-artifact 52c7bd43166f07e1326715639a11f6c1d22d17943f397c10828a0797eee1b986
```

Restaura a imagem anterior congelada `sha256:45fda2f96460b052292a1b323a825f78b8c3ccd78551ae9e21ec2a769d389a31` nos dois containers. Não reverte dados aprovados nem pagamentos.

App, no repositório, após conferir deployments ativos:

```sh
pnpm exec wrangler rollback 46ce4e63-9f15-482e-b0ed-f4472f2bc8b5 --name app-supletivo-net-br
```

Após rollback, conferir health, login e os dois fluxos reais. Registrar a intervenção no oráculo. Nenhum rollback foi necessário nem executado nesta rodada.

## Limites e trabalho ainda necessário

Esta evidência cobre comprovante do próprio titular. CPF presente/divergente, parentesco, justificativa recusada e decisão humana têm regressão automatizada, mas ainda precisam de canários completos com fontes reais adequadas. Não houve homologação do usuário para esses cenários.

Ainda é necessário conferir as notificações de rejeição com tarefa assíncrona real e tratamento da coordenação, definir de forma consistente a política de recência (a tela fala em 90 dias; o prompt atual trata isso como preferência), obter o contato de suporte do backend e alinhar a apresentação completa do endereço ao design canônico. A etapa seguinte do aluno é escolaridade; a assinatura por selfie exige captura ao vivo pelo usuário.
