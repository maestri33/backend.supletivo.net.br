# Reteste real de RG e CNH — 11/10/2026

Atualização posterior: as pendências técnicas de recuperação limitada do OCR, estados de revisão, motivos por etapa e mensagens de PDF foram corrigidas e retestadas na publicação `.92`, preservada pelo backend `.93`. Consulte o [encerramento e evidências atuais](identity-pending-closure-2026-10-12.md). O histórico abaixo preserva as falhas e o estado observado antes dessa correção.

Escopo: documento de identidade do aluno e do candidato a promotor. Os arquivos foram escolhidos na interface de produção, com classificação e análise assíncrona reais na Cloudflare. A preparação e restauração dos estados de canário foram controladas no backend; não representam novos cadastros pela landing. Nenhum teste desta rodada alterou pagamentos ou enviou documentos de endereço/selfie.

Resultado técnico observado: RG completo em JPG/PNG/PDF e RG separado nas duas ordens passaram. A CNH passou no reenvio final `.91`, com identidade conferida e registro/categoria/validade comparados ao original e persistidos. Duas chamadas anteriores do OCR Scout atingiram 60 s e ficaram em revisão: a instabilidade continua aberta e não foi escondida pelo sucesso posterior. Não há homologação de plataforma ou aprovação em nome do usuário.

## Erros antes do caminho feliz

Na UI do aluno, foram rejeitados arquivo vazio, TXT, arquivo acima de 15 MB, JPG corrompido, PDF corrompido, PDF protegido por senha, PDF com três páginas, PNG vazio, imagem ilegível e CNH. A matrícula aceita somente RG. Esses dez testes ocorreram na `.88`; o backend não recebeu fontes de identidade após eles.

No pipeline real, o RG original também foi rejeitado ao testar um nome esperado completamente divergente. O documento não foi alterado; o nome do cadastro foi restaurado. Task `dd83869e416549988861faa7ec7d3287`, concluída às `20:51:27.800564Z`, resultado `rejected`, `identity_checks.name=mismatch`.

Um RG correto falhou depois na `.88`: a resposta de OCR não continha JSON estruturado e o resultado ficou em revisão, sem aprovação falsa. Task `493df2068d7a457fb0c20ebb9403bc88`, concluída às `20:54:09.633172Z`. Corrigimos o gateway e o leitor e publicamos a `.89` antes de retomar o caminho feliz. A correção encaminha as opções de JSON, desliga o raciocínio do Gemma por padrão, preserva o resultado upstream e permite no máximo duas tentativas de extração.

Na UI real do candidato `.89`, os mesmos nove arquivos inválidos foram rejeitados (sem o caso CNH, que é permitido neste papel). Após os nove erros, `candidate.doc_type` seguia nulo e a CNH não tinha fontes armazenadas. A CNH real foi depois rejeitada pelo nome esperado divergente: Task `02248608881a4040890ea496f12c544a`, de `21:12:35.706580Z` a `21:13:36.148797Z`, `identity_checks.name=mismatch`. O nome original foi restaurado antes do reenvio feliz.

## Caminhos felizes de RG na `.89`

| Envio pela UI | Resultado | Task final |
| --- | --- | --- |
| Frente e verso juntos em PNG | Aprovado; uma fonte `full`; não pediu outro arquivo | `97050aceaa0b4c7a868be242a7180e72` |
| Frente e verso juntos em PDF | Aprovado; uma fonte `full`; não pediu outro arquivo | `9eb263ca621044658a05cdf0c7345496` |
| Frente → recarregar → verso | Aprovado; primeiro lado preservado | `400324ed53924cb2b1553bf503522e85` |
| Verso → recarregar → frente | Aprovado; pediu somente o lado faltante | `28af36113696488289b20edbe3dc4755` |

Nos quatro casos, nome, CPF e nascimento conferiram. A persistência confirmou número do RG igual à transcrição, órgão emissor, expedição, filiação e naturalidade. Nacionalidade permaneceu vazia quando não estava impressa; não foi inventada.

Repetir a frente quando o app pedia verso mostrou “Esse lado já foi recebido. Envie o verso do RG.” A proteção adicional no backend retornou `DOCUMENT_SIDE_DUPLICATE` ao tentar enviar os mesmos bytes como verso, sem gravar o verso nem remover a frente.

Os avisos de aprovação foram encontrados no WhatsApp do servidor via GOWA: PNG `3EB0B90F521F5285BE68B6` (`21:01:18Z`), PDF `3EB06DEB9B841488C164F6` (`21:02:37Z`), frente→verso `3EB0263968C01C9A9A66BE` (`21:07:26Z`), verso→frente `3EB0477F46E57EBFD27617` (`21:09:04Z`). As rejeições por nome também produziram aviso: RG `3EB0804E17E544F8A79A46` e CNH `3EB0AE1F5737B3FE4CE7D7`.

## Verificações determinísticas separadas

19/19 verificações passaram dentro do contêiner de produção: 14 mutações controladas de campos do OCR real salvo (nome, casamento, CPF e nascimento) e cinco casos de decoder de arquivo. Esses casos não chamaram IA nem alteraram banco. A prova de OCR/UI é a matriz de canários acima, não essa contagem.

Na primeira etapa, 80 testes locais de backend e 27 de frontend passaram. O gate final `.91` passou em 137 testes de backend. Eles usam adaptadores offline/falhas controladas e são registrados separadamente; não substituem os canários reais.

## Evidência e limites

- [Evidência final de release, persistência e limpeza](identity-retest-v91-evidence.json)
- [Registro histórico `.89`](identity-retest-v89-evidence.json)
- [Casos pela UI real](identity-retest-ui-2026-10-11.json)
- [Verificação local](identity-retest-local-tests-2026-10-11.json)
- [Release e rollback](role-pipeline-release-2026-10-11.md)

Uma matriz finita e documentos de uma pessoa não demonstram todos os erros possíveis nem precisão universal da IA. CPF ausente comprovadamente no documento tem regra diferente de CPF ilegível/incerto; a incerteza exige revisão. Variações de sobrenome por casamento foram verificadas nas regras de comparação, sem fabricar documentos. Endereço, selfie ao vivo, contrato e ativação completa permanecem fora desta rodada. Apenas o usuário homologa a entrega.

## Falhas adicionais encontradas na CNH

A CNH `.89` foi marcada como aprovada com nome/CPF/nascimento corretos, mas a conferência com o PDF original revelou número de identidade copiado como registro e categoria incorreta. Task `a7602bae46e14bc391ca2c8f9a03594b`, concluída às `21:14:51.304493Z`. Isso é uma falha do caminho feliz, e não aceitação do teste.

A `.90` manteve o OCR de identidade Scout e acrescentou leitura visual Gemma focada somente em registro/categoria, com fonte inteira e quatro recortes, sem dados esperados da conta no prompt. Registros malformados/categorias ilegíveis não são preenchidos; RENACH incerto não recebe um código numérico indevido. O probe real dessa leitura conferiu os dois campos com o original. 117 testes de backend e 27 de frontend passaram; preflight sem migrações; backend publicado às `21:23:57.805572Z`, artifact `fa83ef8b9e727250882a611fccf6e161cbc4988522f209b9d47b902f6ac75a78`, app Worker `a0033036-e403-491b-8ffe-abab1a275fc8`.

O canário real `.90` teve timeout de rede do OCR Scout depois de 60089 ms e ficou corretamente em `review`, sem aplicar dados ou aprovar. Task `97875c27d5c24d08b76bfb4f44676201`, concluída às `21:25:58.869694Z`. A revisão de código também identificou que um reenvio podia manter credenciais antigas incorretas por preencher somente campos vazios.

## Publicação `.91` e indisponibilidade observada

A `.91` exige identidade conferida e registro/categoria válidos antes do preenchimento automático da CNH, inclusive em payloads históricos usados depois de decisão humana. A decisão humana é preservada. Credenciais novas conferidas substituem as antigas; RENACH novo incerto não mantém um valor antigo malformado. O comportamento do RG e o preenchimento de perfil permanecem preservados.

Backend promovido às `2026-10-11T21:35:42.694126Z`, artifact `3466b120c0d98076d5dbe9b3c159326677dc9714a8356ef3140a7a8bfdd69ced`, image `sha256:a30a4ae2976b4767fed6fa40958ee796b43c8a9a8f58545209cf86e314319119`, build `21:31:55.825954Z`. Health identificou a versão `.91`, `db=true`, zero migrações pendentes. Worker do app `aaab7a43-602a-41da-870f-4175d2310301`; build passou; registro do app no oráculo às `21:36:17.872Z`. 137 testes de backend passaram em 10,95 s; 27 testes de identidade do frontend passaram em fonte sem alteração funcional posterior.

O primeiro reenvio `.91` foi feito sobre registro/categoria/RENACH antigos de canário, sem limpar os campos. Task `9a0c7fbbd4484e10bee07f37eb6ec40b`, de `21:36:30.349858Z` a `21:37:32.299410Z`: outro timeout Scout de 60086 ms, resultado `review`, sem extração de identidade nem substituição dos campos. O sucesso da execução de fila não é sucesso do documento.

Um probe posterior sem alteração de cadastro, com o mesmo arquivo, modelo e prompt de OCR e limite HTTP de 110 s, respondeu em 25665 ms, 811 tokens de saída, `finish_reason=stop`. Isso não demonstra que aumentar timeout corrige a causa: essa chamada respondeu antes de 60 s. A latência/indisponibilidade intermitente continua sendo risco observado. Foi reservado um único novo reenvio real depois desse probe; não há repetição ilimitada até conseguir aprovação.

Rollback do backend: `/opt/v7m-platform/releases/identity-cnh-persist-20261011-v91/release.py rollback --expected-artifact 3466b120c0d98076d5dbe9b3c159326677dc9714a8356ef3140a7a8bfdd69ced`, restaura web/qcluster `.90`, sem rollback de banco. Rollback do app para Worker `.90` `a0033036-e403-491b-8ffe-abab1a275fc8`. O gateway continua na `.89`, Worker `96bc4518-859e-404f-9eb3-202e3e4bcb56`.

## Reteste final e encerramento do contexto temporário

RG JPG original inteiro: Task `fe98f9dc6f8348dfaba01c3805ca6353`, de `2026-10-12T01:49:56.028999Z` a `01:50:08.123377Z` (ainda 11/10 no fuso de São Paulo). Aprovado, uma fonte `full`, nome/CPF/nascimento `match`, número persistido igual à transcrição. A UI mostrou “RG aprovado” e “Frente e verso recebidos no mesmo arquivo”, sem pedir outro lado.

CNH original no reenvio final `.91`: Task `765db6dc57d0467bb997c0098dfbece1`, de `2026-10-12T01:51:07.531874Z` a `01:51:41.389052Z`. Aprovada, uma fonte `full`, nome/CPF/nascimento `match`. A comparação privada com o PDF confirmou registro de 11 dígitos, categoria e validade corretos **tanto na extração quanto no banco**. Registro/categoria antigos do canário foram substituídos; RENACH ilegível/incerto ficou nulo e o valor numérico antigo malformado foi removido. Não declarar que todo campo foi extraído: RENACH continua ausente. Dados de perfil já presentes foram preservados.

Latências da CNH final: visão Gemma 1167 ms; OCR Scout 26953 ms; estruturação Llama 3587 ms; leitura de credenciais Gemma 1627 ms. Todos os modelos são Workers AI Cloudflare. Não houve mudança de timeout/configuração para produzir esse sucesso. A UI mostrou “Identidade conferida” e o número da CNH; a exibição automática do próximo campo não constitui teste de endereço.

GOWA encontrou os avisos enviados: RG JPG `3EB03E71CB17FCDB1D4C44` (`2026-10-12T01:50:09Z`) e CNH `3EB064B0CB7EB3CECA615C` (`01:51:43Z`). O export da UI terminou com **35 registros de casos/eventos**, não 35 matrículas completas.

O candidato e o usuário de estacionamento criados exclusivamente para esta rodada foram removidos; o papel temporário foi revogado, o promotor histórico suspenso foi religado ao proprietário original e os tokens antigos foram invalidados. Victor permanece aluno com os papéis originais admin/enrollment/staff. Diandra permanece coordenadora do polo padrão e promotora padrão ativa. A cobrança paga, proposta congelada de R$ 1,01/R$ 1,02, comissão pendente de R$ 0,01 e registro anterior de repasse pago foram preservados. Preços e comissões comerciais permaneceram R$ 1615/R$ 100/R$ 500/R$ 50. Os RG/CNH reais aprovados permanecem armazenados; não foi apagado o aluno pago.

Pendências registradas: intermitência do Scout com revisão segura; motivo antigo de comprovante visível no bloco global do candidato durante a identidade; texto “estamos conferindo” ainda exibido quando a CNH já estava em revisão; mensagem genérica para PDF protegido/excessivo. São limites observados, sem declaração de fluxo completo pronto. Endereço, selfie ao vivo, assinatura e ativação integral exigem sua própria rodada.

Issues atualizadas e mantidas abertas: [backend #22 — resultado, correções e estabilidade do OCR](https://github.com/maestri33/backend.supletivo.net.br/issues/22#issuecomment-6116412158) e [app #17 — matriz real e pendências dos estados de UI](https://github.com/maestri33/app.supletivo.net.br/issues/17#issuecomment-6116412517). Os comentários são autossuficientes; a documentação local não foi apresentada como commit publicado nesta rodada. O navegador ficou no RG aprovado após novo login por OTP lido via GOWA.
