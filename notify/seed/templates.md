# Catálogo-base das notificações (seed do DB). Editável pelo Victor.
# Formato: [event:<slug>] + cabeçalho 'chave: valor' + body Markdown cercado por '~~~'.
# Placeholders: {nome} (1º nome), {nome-completo} (nome todo), {valor}, {link}, ...

[event:candidate.awaiting_approval]
channels: whatsapp,email
title: Novo candidato aguardando aprovação
subject: Supletivo Brasil — {candidato_nome} concluiu o cadastro e aguarda sua aprovação
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.candidate
delay_minutes: 0
active: true
~~~
{name}, o candidato {candidato_nome} ({candidato_telefone}) concluiu o cadastro no polo {polo_nome} e aguarda a sua aprovação para virar promotor.

Confira os dados e aprove pelo painel:
{link_painel}
~~~

[event:candidate.doc_type_reset]
channels: whatsapp,email
title: Reenvio de documento liberado
subject: Supletivo Brasil — Seu reenvio de documento foi liberado
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.candidate
delay_minutes: 0
active: true
~~~
{name}, liberamos o reenvio do seu documento — pode mandar a foto do tipo certo (RG ou CNH). É só subir de novo pelo aplicativo, {name}. 📄
~~~

[event:candidate.document_approved]
channels: whatsapp,email
title: Documento aprovado
subject: Supletivo Brasil — Seu documento foi aprovado com sucesso! ✅
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.candidate
delay_minutes: 0
active: true
~~~
Pode seguir, {name}! ✅ Seu documento foi aprovado e o cadastro segue em frente. Continue o preenchimento, {name}.
~~~

[event:candidate.document_in_review]
channels: whatsapp,email
title: Documento de candidato em análise
subject: Supletivo Brasil — Documento de {candidato_nome} precisa da sua análise
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.candidate
delay_minutes: 0
active: true
~~~
{name}, o documento ({doc_tipo}) do candidato {candidato_nome} ({candidato_telefone}) precisa da sua análise — a IA ficou em dúvida.

Aprove ou reprove pelo painel:
{link_painel}
~~~

[event:candidate.document_rejected]
channels: whatsapp,email
title: Documento precisa ser reenviado
subject: Supletivo Brasil — Precisamos de uma nova foto do seu documento 📄
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.candidate
delay_minutes: 0
active: true
~~~
{name}, precisamos de uma nova foto do seu documento: {detail}

Reenvie pelo aplicativo, {name} — é rapidinho:
{link_app}
~~~

[event:candidate.rejected]
channels: whatsapp,email
title: Cadastro não aprovado
subject: Supletivo Brasil — Informações sobre o seu cadastro de colaborador
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.candidate
delay_minutes: 0
active: true
~~~
{name}, seu cadastro de colaborador não foi aprovado neste momento. Motivo: {motivo}

Fale com o coordenador do seu polo {polo_nome} ({polo_contato}) para entender os próximos passos, {name}.
~~~

[event:candidate.selfie_approved]
channels: whatsapp,email
title: Selfie aprovada
subject: Supletivo Brasil — Sua selfie foi confirmada! ✅
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.candidate
delay_minutes: 0
active: true
~~~
Aprovado, {name}! ✅ Sua selfie foi confirmada e o cadastro segue em frente. Continue o preenchimento, {name}.
~~~

[event:candidate.selfie_in_review]
channels: whatsapp,email
title: Selfie de candidato em análise
subject: Supletivo Brasil — Selfie de {candidato_nome} precisa da sua análise
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.candidate
delay_minutes: 0
active: true
~~~
{name}, a selfie do candidato {candidato_nome} ({candidato_telefone}) no polo {polo_nome} precisa da sua análise — a IA ficou em dúvida.

Aprove ou reprove pelo painel:
{link_painel}
~~~

[event:candidate.selfie_rejected]
channels: whatsapp,email
title: Selfie precisa ser reenviada
subject: Supletivo Brasil — Precisamos de uma nova selfie
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.candidate
delay_minutes: 0
active: true
~~~
{name}, sua selfie não pôde ser confirmada. Envie uma nova foto pelo aplicativo, nítida e mostrando bem o rosto, {name}:
{link_app}
~~~

[event:enrollment.awaiting_release]
channels: whatsapp,email
title: Matrícula aguarda liberação
subject: Supletivo Brasil — Matrícula de {aluno_nome} aguarda liberação
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.enrollment
delay_minutes: 0
active: true
~~~
{name}, a matrícula do aluno {aluno_nome} ({aluno_telefone}) no polo {polo_nome} concluiu o envio de dados e aguarda a sua liberação.

Confira os documentos e libere pelo painel:
{link_painel}
~~~

[event:enrollment.credentials]
channels: whatsapp,email
title: Seus dados de acesso à plataforma
subject: Supletivo Brasil — Seu login e senha de acesso chegaram! 📚
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.enrollment
delay_minutes: 0
active: true
~~~
{name}, aqui estão seus dados de acesso à plataforma de estudos:

🔗 {link}
👤 Login: {login}
🔑 Senha: {password}

Guarde com você, {name} — é por aqui que você entra nas suas aulas. Bons estudos! 📚
~~~

[event:enrollment.fee_due_paid]
channels: whatsapp,email
title: 2ª parcela da taxa paga
subject: Supletivo Brasil — 2ª parcela da taxa de {student_name} foi paga ✅
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.enrollment
delay_minutes: 0
active: true
~~~
{name}, a 2ª parcela da taxa de {student_name} ({valor}) foi PAGA no vencimento. ✅ Taxa quitada, {name} — nada mais a fazer.
~~~

[event:enrollment.fee_paid]
channels: whatsapp,email
title: 1ª parcela da taxa paga
subject: Supletivo Brasil — 1ª parcela de {student_name} paga! Liberar acesso
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.enrollment
delay_minutes: 0
active: true
~~~
{name}, a 1ª parcela da taxa de {student_name} foi PAGA ({valor}). ✅ A instituição já pode liberar o login e a senha — conclua a matrícula no painel, {name}.
~~~

[event:enrollment.fee_problem]
channels: whatsapp,email
title: Problema na taxa de matrícula
subject: Supletivo Brasil — Problema no pagamento da taxa de {student_name}
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.enrollment
delay_minutes: 0
active: true
~~~
{name}, deu problema na taxa de {student_name}: {detail} Confira no painel, {name}, e tente de novo se for o caso.
~~~

[event:enrollment.fee_scheduled]
channels: whatsapp,email
title: 2ª parcela da taxa agendada
subject: Supletivo Brasil — 2ª parcela de {student_name} agendada
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.enrollment
delay_minutes: 0
active: true
~~~
{name}, a 2ª parcela da taxa de {student_name} ({valor}) foi agendada para {due_date}. O pagamento sai sozinho no vencimento, {name}.
~~~

[event:enrollment.released]
channels: whatsapp,email
title: Sua matrícula foi liberada!
subject: Supletivo Brasil — Bem-vindo(a)! Sua matrícula foi liberada 💚
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.enrollment
delay_minutes: 0
active: true
~~~
{name}, é oficial: você é nosso aluno! 💚 Sua matrícula foi liberada. Seja muito bem-vindo(a), {name} — a sua escola estava esperando por você.
~~~

[event:enrollment.rg_approved]
channels: whatsapp,email
title: RG aprovado
subject: Supletivo Brasil — Seu documento foi aprovado com sucesso! ✅
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.enrollment
delay_minutes: 0
active: true
~~~
Tudo certo, {name}! ✅ Seu RG foi aprovado e sua matrícula segue em frente. Continue o preenchimento, {name}.
~~~

[event:enrollment.rg_in_review]
channels: whatsapp,email
title: RG de matrícula em análise
subject: Supletivo Brasil — RG de {aluno_nome} precisa da sua análise
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.enrollment
delay_minutes: 0
active: true
~~~
{name}, o RG do aluno {aluno_nome} ({aluno_telefone}) no polo {polo_nome} precisa da sua análise: {detail}

Aprove ou reprove pelo painel:
{link_painel}
~~~

[event:enrollment.rg_rejected]
channels: whatsapp,email
title: RG precisa ser reenviado
subject: Supletivo Brasil — Precisamos de uma nova foto do seu RG 📄
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.enrollment
delay_minutes: 0
active: true
~~~
{name}, precisamos de uma nova foto do seu RG: {detail}

Reenvie pelo aplicativo, {name} — é rapidinho:
{link_app}
~~~

[event:enrollment.selfie_approved]
channels: whatsapp,email
title: Matrícula assinada com sucesso
subject: Supletivo Brasil — Sua matrícula foi assinada! ✍️
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.enrollment
delay_minutes: 0
active: true
~~~
{name}, sua matrícula está assinada. ✍️ E quem assinou foi você, com o seu próprio rosto — ninguém fez isso por você. Esse passo é seu pra sempre, {name}. Agora é com a gente: assim que estiver tudo conferido, a gente te avisa por aqui.
~~~

[event:enrollment.selfie_in_review]
channels: whatsapp,email
title: Selfie de matrícula em análise
subject: Supletivo Brasil — Selfie de {aluno_nome} precisa da sua análise
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.enrollment
delay_minutes: 0
active: true
~~~
{name}, a selfie do aluno {aluno_nome} ({aluno_telefone}) no polo {polo_nome} precisa da sua análise — a IA ficou em dúvida.

Aprove ou reprove pelo painel:
{link_painel}
~~~

[event:enrollment.selfie_rejected]
channels: whatsapp,email
title: Selfie precisa ser reenviada
subject: Supletivo Brasil — Precisamos de uma nova selfie para sua matrícula
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.enrollment
delay_minutes: 0
active: true
~~~
{name}, sua selfie não pôde ser confirmada. Envie uma nova foto pelo aplicativo, nítida e mostrando bem o rosto, {name}:
{link_app}
~~~

[event:hub.coordinator_assigned]
channels: whatsapp,email
title: Nomeação de coordenação de polo
subject: Supletivo Brasil — Você agora é coordenador(a) do polo {polo_nome}! 🎉
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: hub.interface
delay_minutes: 0
active: true
~~~
Parabéns, {name}! Você agora é COORDENADOR(A) do polo {polo_nome}. {name}, acompanhe as matrículas, revise documentos e libere os alunos pelo painel:
{link_painel}
~~~

[event:lead.captured]
channels: whatsapp,email
title: Bem-vindo(a) ao Supletivo Brasil!
subject: Supletivo Brasil — Seu cadastro foi iniciado! Falta só um passo
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.lead
delay_minutes: 0
active: true
~~~
Olá, {name}! Que bom ter você com a gente. Seu cadastro está pronto, {name} — falta só um passo pra garantir sua vaga: concluir o pagamento. Em instantes envio o link. Bora juntos nessa jornada!
~~~

[event:lead.captured.promoter]
channels: whatsapp,email
title: Novo lead na sua rede
subject: Supletivo Brasil — {lead_nome} entrou na sua indicação! 🚀
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.lead
delay_minutes: 0
active: true
~~~
Boa notícia, {name}! {lead_nome} ({lead_telefone}) acabou de entrar na sua rede pela sua indicação. 🚀

Chame agora no WhatsApp para tirar dúvidas e incentivar a concluir a matrícula:
{lead_whatsapp_url}

Bora fechar mais essa comissão, {name}! 👊
~~~

[event:lead.checkout.card]
channels: whatsapp,email
title: Link de pagamento da sua matrícula
subject: Supletivo Brasil — Link para pagamento no cartão ({valor})
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.lead
delay_minutes: 0
active: true
~~~
{name}, para concluir sua matrícula pague {valor} no cartão:
{link}

Qualquer dúvida é só chamar, {name}.
~~~

[event:lead.checkout.pix]
channels: whatsapp,email
title: PIX da sua matrícula
subject: Supletivo Brasil — Código PIX para pagamento ({valor})
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.lead
delay_minutes: 0
active: true
~~~
{name}, para concluir sua matrícula pague o PIX de {valor}:
{link}

Ou use o PIX copia-e-cola, {name}:
{payload}
~~~

[event:lead.paid]
channels: whatsapp,email
title: Matrícula confirmada!
subject: Supletivo Brasil — Pagamento confirmado! Inicie seus documentos 🎉
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.lead
delay_minutes: 0
active: true
~~~
Parabéns, {name}! 🎉 Seu pagamento foi confirmado e sua matrícula começou. Você deu um passo importante, {name} — acesse para preencher seus documentos: {docs_link}
~~~

[event:lead.paid.coordinator]
channels: whatsapp,email
title: Nova matrícula no seu polo!
subject: Supletivo Brasil — Nova matrícula no polo {polo_nome} ({aluno_nome})
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.lead
delay_minutes: 0
active: true
~~~
{name}, uma nova matrícula entrou no polo {polo_nome}!

Aluno: {aluno_nome} ({aluno_telefone})
Acompanhe o acolhimento pedagógico e o envio de documentos pelo painel:
{link_painel}
~~~

[event:lead.paid.promoter]
channels: whatsapp,email
title: Matrícula paga por sua indicação!
subject: Supletivo Brasil — Seu indicado {aluno_nome} pagou a matrícula! ✅
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.lead
delay_minutes: 0
active: true
~~~
{name}, seu indicado {aluno_nome} ({aluno_telefone}) pagou a matrícula! ✅

Comissão de {comissao_direta} garantida.
Total na semana: {leads_semana} (meta: {meta_bonus}). Faltam {falta_para_bonus} para o bônus semanal! 💸

Dê os parabéns ao novo aluno no WhatsApp:
{aluno_whatsapp_url}
~~~

[event:lead.paid.receipt]
channels: whatsapp,email
title: Comprovante de pagamento
subject: Supletivo Brasil — Comprovante de pagamento ({valor})
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.lead
delay_minutes: 0
active: true
~~~
{name}, aqui está o comprovante do seu pagamento de {valor}:
{link}
Guarde para referência, {name}.
~~~

[event:promoter.reactivated]
channels: whatsapp,email
title: Atuação de promotor reativada
subject: Supletivo Brasil — Sua conta de promotor foi reativada! 🚀
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.promoter
delay_minutes: 0
active: true
~~~
Que bom te ver de volta, {name}! Sua atuação como promotor foi reativada. {name}, seu link de captação está ativo de novo — bora!
~~~

[event:promoter.suspended]
channels: whatsapp,email
title: Atuação de promotor suspensa
subject: Supletivo Brasil — Aviso sobre sua conta de promotor
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.promoter
delay_minutes: 0
active: true
~~~
{name}, sua atuação como promotor foi temporariamente suspensa pelo coordenador do polo. Fale com o coordenador para regularizar, {name}.
~~~

[event:student.diploma_issued]
channels: whatsapp,email
title: Seu diploma está pronto!
subject: Supletivo Brasil — Parabéns! O seu diploma foi emitido! 🎓
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.student
delay_minutes: 0
active: true
~~~
{name}, chegou o grande dia: o seu diploma está pronto! 🎓 Você terminou os seus estudos — o que um dia ficou para trás, hoje você concluiu. E isso é seu para sempre, {name}. Parabéns! A gente tem muito orgulho de você.
~~~

[event:student.diploma_pickup]
channels: whatsapp,email
title: Retirada de diploma liberada
subject: Supletivo Brasil — Seu diploma já pode ser retirado no polo! 🎓
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.student
delay_minutes: 0
active: true
~~~
Para retirar o seu diploma, {name}, é só procurar o coordenador do seu polo {polo_nome}. Ele já está esperando por você, {name}.
~~~

[event:student.document_in_review]
channels: whatsapp,email
title: Documento de aluno em análise
subject: Supletivo Brasil — Documento ({doc_type}) de {aluno_nome} em análise
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.student
delay_minutes: 0
active: true
~~~
{name}, o documento ({doc_type}) do aluno {aluno_nome} ({aluno_telefone}) no polo {polo_nome} precisa da sua análise — a IA ficou em dúvida.

Aprove ou reprove pelo painel:
{link_painel}
~~~

[event:student.document_rejected]
channels: whatsapp,email
title: Documento precisa ser reenviado
subject: Supletivo Brasil — Precisamos de uma nova foto do seu documento ({doc_type})
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.student
delay_minutes: 0
active: true
~~~
{name}, seu documento ({doc_type}) precisa ser reenviado. Envie uma nova foto, nítida e legível, {name}.{reason_text}

Acesse pelo aplicativo para enviar:
{link_app}
~~~

[event:student.exam_failed]
channels: whatsapp,email
title: Resultado da sua prova
subject: Supletivo Brasil — Resultado da sua prova e próximos passos
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.student
delay_minutes: 0
active: true
~~~
{name}, você não atingiu a nota desta vez — mas não desanime. Reagende para uma nova tentativa, {name}, você consegue!
~~~

[event:student.exam_passed]
channels: whatsapp,email
title: Aprovado na prova final!
subject: Supletivo Brasil — Você foi APROVADO(A) na prova! 🎉
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.student
delay_minutes: 0
active: true
~~~
Você foi APROVADO na prova, {name}! 🎉 Estamos finalizando a sua documentação, {name}. Falta pouco!
~~~

[event:student.exam_released]
channels: whatsapp,email
title: Prova final liberada para agendamento!
subject: Supletivo Brasil — Seus documentos foram aprovados! Agende sua prova 📅
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.student
delay_minutes: 0
active: true
~~~
{name}, seus documentos foram aprovados! Você já pode agendar a sua prova quando quiser, {name}.
~~~

[event:student.exam_scheduled]
channels: whatsapp,email
title: Prova de aluno agendada
subject: Supletivo Brasil — {aluno_nome} agendou a prova final no polo {polo_nome}
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.student
delay_minutes: 0
active: true
~~~
{name}, o aluno {aluno_nome} ({aluno_telefone}) do polo {polo_nome} agendou a prova e aguarda a sua correção.

Confira os detalhes no painel:
{link_painel}
~~~

[event:student.pendency_opened]
channels: whatsapp,email
title: Pendência na sua matrícula
subject: Supletivo Brasil — Há uma pendência para resolver na sua matrícula
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.student
delay_minutes: 0
active: true
~~~
{name}, há uma pendência na sua matrícula: {detail}. Resolva para seguir com a emissão do diploma, {name}.
~~~

[event:student.veteran]
channels: whatsapp,email
title: Parabéns, veterano(a)!
subject: Supletivo Brasil — Você concluiu seus estudos e agora é veterano(a)! 🎓💚
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.student
delay_minutes: 0
active: true
~~~
{name}, agora você é veterano da nossa escola. 💚 Você chegou até o fim — e quem chega ao fim inspira quem ainda está começando. Bem-vindo ao time, {name}!
~~~

[event:student.veteran.coordinator]
channels: whatsapp,email
title: Aluno diplomado no polo!
subject: Supletivo Brasil — {aluno_nome} formou e foi diplomado no polo {polo_nome}! 🎓
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.student
delay_minutes: 0
active: true
~~~
{name}, o aluno {aluno_nome} ({aluno_telefone}) do polo {polo_nome} se formou e foi diplomado com sucesso! ✅

Sua comissão entra no próximo fechamento semanal, {name}. 💸
~~~

[event:training.approved]
channels: whatsapp,email
title: Treinamento aprovado — Você é promotor!
subject: Supletivo Brasil — Parabéns! Você foi aprovado e agora é PROMOTOR 🎉
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.training
delay_minutes: 0
active: true
~~~
Parabéns, {name}! 🎉 Você foi aprovado e agora é PROMOTOR. {name}, seu link de captação já está ativo — comece a indicar e a ganhar!
~~~

[event:training.cleared]
channels: whatsapp,email
title: Treinamento concluído
subject: Supletivo Brasil — Painel liberado e link de captação ativo! 🚀
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.training
delay_minutes: 0
active: true
~~~
Treinamento concluído, {name}! 🎉 Seu painel está liberado e seu link de captação ativo. Agora é com você, {name} — comece a indicar e a ganhar!
~~~

[event:training.must_train]
channels: whatsapp,email
title: Conclua seu treinamento de promotor
subject: Supletivo Brasil — Falta pouco! Conclua o treinamento para ativar seu painel
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.training
delay_minutes: 0
active: true
~~~
Parabéns, {name}! Você foi aprovado e agora é PROMOTOR. Antes de liberar seu painel, {name}, conclua o treinamento obrigatório no aplicativo — assim que terminar, tudo é liberado.
~~~

[event:training.new_material]
channels: whatsapp,email
title: Novo treinamento disponível
subject: Supletivo Brasil — Novo treinamento obrigatório disponível no app
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.training
delay_minutes: 0
active: true
~~~
{name}, há um novo treinamento obrigatório no aplicativo. Conclua a atividade para continuar usando o painel, {name}.
~~~

[event:candidate.address_proof_rejected]
channels: whatsapp,email
title: Comprovante de endereço precisa ser reenviado
subject: Supletivo Brasil — precisamos de outro comprovante de endereço
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.candidate
delay_minutes: 0
active: true
~~~
{name}, recebemos o arquivo, mas ele não pôde ser aceito como comprovante de endereço.

Motivo: {detail}

Envie pelo aplicativo uma conta ou documento recente que mostre o endereço completo. O restante do seu cadastro continua salvo, {name}.
~~~

[event:lead.paid.promoter.scholarship]
channels: whatsapp,email
title: Sua indicação avançou sua bolsa
subject: Supletivo Brasil — sua indicação pagou e sua bolsa avançou
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.lead
delay_minutes: 0
active: true
~~~
Boa notícia, {name}: sua indicação virou uma matrícula paga! ✅ A comissão já entrou no próximo fechamento semanal. {progress_text} Continue firme, {name}.
~~~

[event:promoter.scholarship_enrolled]
channels: whatsapp,email
title: Sua bolsa foi efetivada
subject: Supletivo Brasil — suas três matrículas efetivaram sua bolsa
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.promoter
delay_minutes: 0
active: true
~~~
Você conseguiu, {name}! 🎓 Suas {enroll_goal} matrículas pagas efetivaram sua bolsa e sua matrícula como aluno começou sem cobrança. Agora siga o fluxo normal de estudos e documentos. Ao chegar a {exam_goal} matrículas pagas, você cumpre o requisito de indicações para a prova final. Parabéns por essa conquista, {name}!
~~~

[event:training.approved.scholarship]
channels: whatsapp,email
title: Promotor ativo e trilha da bolsa iniciada
subject: Supletivo Brasil — seu acesso está ativo e sua trilha da bolsa começou
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.training
delay_minutes: 0
active: true
~~~
Deu certo, {name}! 🎉 Seu acesso de promotor está ativo e você também entrou na trilha da bolsa. Seu link exclusivo já está no painel. Ao conquistar {enroll_goal} matrículas pagas, sua própria matrícula como aluno é efetivada; com {exam_goal}, você cumpre o requisito de indicações para a prova final. Você pode transformar outras vidas e retomar seus estudos, {name}.
~~~

[event:training.must_train.scholarship]
channels: whatsapp,email
title: Treinamento e trilha da bolsa
subject: Supletivo Brasil — conclua o treinamento para iniciar sua trilha
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.training
delay_minutes: 0
active: true
~~~
Você foi aprovado, {name}! 🎉 Além do acesso de promotor, você entrou na trilha da bolsa. Primeiro, conclua o treinamento obrigatório no aplicativo; depois, seu link será liberado. Com {enroll_goal} matrículas pagas sua matrícula como aluno é efetivada, e com {exam_goal} você cumpre o requisito de indicações da prova final, {name}.
~~~

[event:auth.otp]
channels: whatsapp,email
title: Código de verificação
subject: Seu código de acesso Supletivo Brasil
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.auth.otp
delay_minutes: 0
active: true
~~~
Olá! Seu código de verificação é: *{codigo}*

Este código expira em *{ttl_minutos}* minutos.

Se você não solicitou este acesso, ignore esta mensagem.
~~~

[event:auth.cpf_conflict]
channels: whatsapp,email
title: Alerta de segurança
subject: Tentativa de uso do seu CPF no Supletivo Brasil
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.auth
delay_minutes: 0
active: true
~~~
🔒 Alguém tentou usar o seu CPF para criar um cadastro no Supletivo Brasil em {data} às {hora}, com o número {numero}. O cadastro foi bloqueado e desfeito automaticamente. Se não foi você, fale com o nosso suporte por este WhatsApp.
~~~

[event:finance.commission_paid]
channels: whatsapp,email
title: Comissão paga
subject: Sua comissão foi paga! 💸
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: finance.payout
delay_minutes: 0
active: true
~~~
Olá, {nome}! Sua comissão foi paga. 💸

Acabamos de enviar o PIX de R$ {valor} referente ao fechamento da sua semana. O valor deve cair na sua conta em instantes.
~~~

[event:lead.payment_reminder]
channels: whatsapp,email
title: Sua matrícula está quase lá
subject: Lembrete de pagamento da sua matrícula
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.lead
delay_minutes: 0
active: true
~~~
Olá, {nome}! Passando pra lembrar que a sua matrícula no Supletivo Brasil ainda está aguardando o pagamento. 😊

É rapidinho, pelo link: {payment_link}

Se já pagou, pode ignorar esta mensagem — a confirmação é automática. Qualquer dúvida, é só responder aqui que um atendente te ajuda.
~~~

[event:promoter.lead_invite]
channels: whatsapp,email
title: Convite Supletivo Brasil
subject: Você recebeu um convite para conhecer o Supletivo
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.promoter
delay_minutes: 0
active: true
~~~
Você recebeu um convite para conhecer o Supletivo Brasil.

Acesse com segurança pelo link: {link}

Você confirma seus próprios dados antes de qualquer matrícula.
~~~

[event:enrollment.concluded_referral]
channels: whatsapp,email
title: Nova matrícula concluída por indicação!
subject: Supletivo Brasil — Sua indicação {aluno_nome} concluiu a matrícula! 🎓
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.student
delay_minutes: 0
active: true
~~~
Parabéns, {name}! Sua indicação {aluno_nome} ({aluno_telefone}) concluiu a matrícula e agora é oficialmente ALUNO do Supletivo Brasil! 🎓

Sua comissão está garantida e entra no próximo fechamento semanal. Continue compartilhando seu link! 🚀
~~~

[event:enrollment.address_proof_rejected]
channels: whatsapp,email
title: Comprovante de residência precisa de ajuste
subject: Supletivo Brasil — Ajuste no comprovante de endereço
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.enrollment
delay_minutes: 0
active: true
~~~
{name}, seu comprovante de residência não pôde ser aceito. Motivo: {motivo}

Envie pelo aplicativo uma conta recente no seu nome ou de parente direto:
{link_app}
~~~

[event:training.submission_rejected]
channels: whatsapp,email
title: Atividade precisa de revisão
subject: Supletivo Brasil — Sua atividade em {materia_titulo} precisa de ajuste
media_url: 
media_type: 
mail_template: supletivo
fires_on: 
source: users.roles.training
delay_minutes: 0
active: true
~~~
{name}, sua atividade no treinamento ({materia_titulo}) precisa de um ajuste antes de ser aprovada. ✍️

Feedback:
{motivo}

Acesse o aplicativo para enviar novamente e destravar seu painel:
{link_app}
~~~

