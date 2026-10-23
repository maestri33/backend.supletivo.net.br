# Escolaridade aluno/promotor — contrato implementado

## Regra de produto

- O aluno informa o último nível e ano frequentado. Fundamental aceita 1º–9º; Ensino Médio aceita 1º–3º.
- `medio + grade=3 + completed=true` é rejeitado. Parar no 3º ano (`completed=false`) continua permitido.
- O promotor usa a própria taxonomia e pode declarar Ensino Superior completo ou interrompido (graduação,
  pós-graduação, mestrado ou doutorado). A restrição do aluno não é aplicada ao promotor.
- O fluxo exige `declaration_accepted: true`. O backend grava versão `education-v1`, IP, user-agent e horário
  na matrícula ou no candidato antes de avançar para a selfie.
- Cidade e UF são validadas em conjunto contra o catálogo IBGE. O app carrega estados primeiro e municípios
  depois da UF; o backend normaliza espaços e UF para maiúsculas e rejeita pares inválidos.

## Interface entregue

- Aluno: formulário progressivo com escolhas de nível/ano/conclusão, UF → cidade IBGE, escola opcional e bloqueio
  visual do 3º ano concluído.
- Promotor: mesma consulta IBGE, escolaridade superior, série/formação e dados opcionais de escola/ano.
- Ambos: modal final de veracidade, texto específico por papel, checkbox obrigatório, SVG de proteção, animação
  reduzida quando solicitado pelo sistema, foco inicial e foco preso no diálogo.
- A consulta IBGE possui timeout de 8 segundos; falha mantém o formulário bloqueado e explica a recuperação.

## Evidência local

- Backend focado: `29 passed` (`test_education_declaration`, `test_candidate_education`, contratos e E2E de aluno).
- Backend total: `882 passed` após isolar o cache transacional de `PlatformSetting` entre testes; nenhuma falha.
- App: `astro check` — 119 arquivos, 0 erros/avisos; `check-types` sem erros; unitários 33/33.
- E2E local: `19 passed`, incluindo aluno, promotor, IBGE, modal, selfie com câmera, documentos, prova e veterano.

## Estado de produção

Produção ainda está em `0.0.0-sandbox.94`, com migrations pendentes `0` e SHA `52c7bd...`. Esta alteração ainda não
foi publicada nem homologada com canário real. O release exige aplicar as migrations `0044_education_declaration`
e `0045_profile_education_state`, executar smoke test do aluno e promotor e só então promover a versão global.
