"""Role `student` (+ `veteran`) — §4 item 9: a fase final do funil do ALUNO.

Nasce quando o coordenador LIBERA a matrícula (`enrollment.release`): o aluno entra em
`AWAITING_DOCUMENTS` com os dados da plataforma de estudo. Daí percorre o funil do `specs/student.md`:
envia os documentos (validados por IA, assíncrono) → faz a prova (coordenador corrige) → conferência
de pendências (documento OU taxa) → diploma emitido → retirada (foto) → vira **veteran** e dispara a
**comissão do coordenador do polo** (motor finance, `Source.VETERAN`).

Sub-pacote de `users` (app_label `users`, 1 migration set — igual lead/enrollment/candidate; CONVENTION §2).
"""
