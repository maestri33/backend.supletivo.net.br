"""Config do `student` — documentos obrigatórios + helpers dos prompts/schemás de IA.

Sem valores de dinheiro aqui (a comissão do coordenador é `finance.config.coordinator_amount`, §8).
Os tipos de documento e suas exigências vêm do `specs/student.md` (palavra do dono) + legado.
"""

from __future__ import annotations

from users.roles.student.models import StudentDocument

_T = StudentDocument.Type

# Documentos exigidos de TODO aluno (foto, validados por IA). O militar é condicional ao gênero
# (só homens) — tratado no service, não aqui. Todos precisam estar APROVADOS pra liberar a prova.
# Fotos exigidas (validadas por IA). O TIPO SANGUÍNEO obrigatório é o VALOR (`Student.blood_type`,
# checado no `_maybe_release_exam`), não a foto — então BLOOD_TYPE NÃO entra aqui (spec: "obrigatório
# especificar" = valor). A foto de tipo sanguíneo segue aceita como documento opcional.
REQUIRED_DOC_TYPES: tuple[str, ...] = (
    _T.CERTIFICATE,  # certificado do último ano (obrigatório — spec)
    _T.TRANSCRIPT,  # histórico (obrigatório — spec)
    _T.ADDRESS_PROOF,  # comprovante de endereço (foto, validado por IA)
    _T.ID_CARD,  # documento pessoal / RG (foto, obrigatório)
    _T.BIRTH_CERTIFICATE,  # certidão
)

# Documento exigido só de homens (gate de gênero no service).
MALE_ONLY_DOC_TYPES: tuple[str, ...] = (_T.MILITARY,)

# Descrição por tipo usada na IA de visão.
_DOC_DESC = {
    _T.MILITARY: "um documento de serviço militar (reservista/dispensa)",
    _T.CERTIFICATE: "um certificado de conclusão escolar",
    _T.TRANSCRIPT: "um histórico escolar",
    _T.BLOOD_TYPE: "um documento/cartão indicando o tipo sanguíneo",
    _T.ADDRESS_PROOF: "um comprovante de endereço (conta de consumo/correspondência recente)",
    _T.ID_CARD: "um documento de identidade com foto (RG ou equivalente)",
    _T.BIRTH_CERTIFICATE: "uma certidão (nascimento/casamento)",
}

# Dicas específicas por tipo de documento pro estágio de VISÃO.
_DOC_TYPE_HINT = {
    _T.CERTIFICATE: (
        "um CERTIFICADO DE CONCLUSÃO ESCOLAR brasileiro (ensino fundamental ou médio). "
        "Deve ter: nome da escola, nome do aluno, série/ano concluído, cidade/UF, data e "
        "assinatura/carimbo. NÃO confunda com histórico escolar (lista de matérias/notas)."
    ),
    _T.TRANSCRIPT: (
        "um HISTÓRICO ESCOLAR brasileiro (lista de disciplinas, notas/conceitos, frequência, "
        "anos cursados). Deve ter: nome da escola, nome do aluno, série/ano de cada registro. "
        "NÃO confunda com certificado de conclusão."
    ),
    _T.ADDRESS_PROOF: (
        "um COMPROVANTE DE ENDEREÇO brasileiro recente (conta de luz, água, gás, internet, "
        "telefone, correspondência bancária ou oficial). Deve ter: NOME do titular, ENDEREÇO "
        "completo, DATA de emissão (preferencialmente últimos 90 dias). NÃO aceite recibo "
        "manuscrito, selfie, tela de app sem endereço completo ou documento muito antigo."
    ),
    _T.ID_CARD: (
        "um DOCUMENTO DE IDENTIDADE brasileiro com foto (RG/CIN/CNH/passaporte brasileiro). "
        "Deve ter: FOTO do titular, NOME, DATA DE NASCIMENTO, número do documento e órgão emissor. "
        "NÃO aceite cópia de tela, selfie, foto de outro documento sem os dados pessoais visíveis."
    ),
    _T.BIRTH_CERTIFICATE: (
        "uma CERTIDÃO DE NASCIMENTO (ou casamento) brasileira. Deve ter: nome do REGISTRADO, "
        "DATA DE NASCIMENTO, nome dos PAIS, número de matrícula (novo modelo), cartório, "
        "livro/folha (modelo antigo). NÃO aceite certidão de óbito, RG, ou documento de outra pessoa."
    ),
    _T.BLOOD_TYPE: (
        "um documento/cartão/laudo indicando o TIPO SANGUÍNEO do aluno (A+, A-, B+, B-, AB+, "
        "AB-, O+ ou O-). Pode ser um cartão de doador, laudo laboratorial, prontuário ou "
        "declaração médica. Deve ter: nome do paciente e o tipo sanguíneo explícito."
    ),
    _T.MILITARY: (
        "um DOCUMENTO DE SERVIÇO MILITAR brasileiro (certificado de reservista, certificado de "
        "dispensa, comprovante de alistamento ou situação militar). Deve ter: nome do titular, "
        "situação militar e número do documento."
    ),
}

# Schemas de extração por tipo (OCR + LLM JSON). Sempre incluem name_match/name_reason quando houver
# titular esperado; documentos sem nome próprio (ex.: comprovante de endereço) validam o titular como
# name_match opcional.
_EXTRACT_SCHEMA_CERTIFICATE = (
    "{"
    '"school_name": "nome da escola, string ou null", '
    '"student_name": "nome completo do aluno no documento, string ou null", '
    '"grade": "série/ano concluído (ex.: 9º ano, 3º ano), string ou null", '
    '"year": "ano de conclusão (AAAA), string ou null", '
    '"city": "cidade/UF da escola, string ou null", '
    '"name_match": "sim | nao | duvida", '
    '"name_reason": "explicação curta da comparação dos nomes"'
    "}"
)

_EXTRACT_SCHEMA_TRANSCRIPT = (
    "{"
    '"school_name": "nome da escola, string ou null", '
    '"student_name": "nome completo do aluno no documento, string ou null", '
    '"years": "anos/séries cursados (ex.: 1º a 9º ano), string ou null", '
    '"city": "cidade/UF da escola, string ou null", '
    '"name_match": "sim | nao | duvida", '
    '"name_reason": "explicação curta da comparação dos nomes"'
    "}"
)

_EXTRACT_SCHEMA_ADDRESS_PROOF = (
    "{"
    '"holder_name": "nome do titular do endereço no documento, string ou null", '
    '"street": "rua/logradouro, string ou null", '
    '"number": "número, string ou null", '
    '"complement": "complemento, string ou null", '
    '"neighborhood": "bairro, string ou null", '
    '"city": "cidade, string ou null", '
    '"state": "UF, string ou null", '
    '"zip": "CEP, string ou null", '
    '"issue_date": "data de emissão no formato AAAA-MM-DD ou null", '
    '"utility": "tipo de conta/correspondência (luz/agua/gas/internet/telefone/banco/outro), string ou null", '
    '"name_match": "sim | nao | duvida", '
    '"name_reason": "explicação curta da comparação do titular com o nome esperado"'
    "}"
)

_EXTRACT_SCHEMA_ID_CARD = (
    "{"
    '"number": "número do documento, string ou null", '
    '"issuing_agency": "órgão emissor com UF (ex.: SSP/SP), string ou null", '
    '"issue_date": "data de expedição no formato AAAA-MM-DD ou null", '
    '"name": "nome completo do titular ou null", '
    '"birth_date": "data de nascimento no formato AAAA-MM-DD ou null", '
    '"mother_name": "nome da mãe (filiação) ou null", '
    '"father_name": "nome do pai (filiação) ou null", '
    '"birthplace": "naturalidade (cidade/UF) ou null", '
    '"name_match": "sim | nao | duvida", '
    '"name_reason": "explicação curta da comparação dos nomes"'
    "}"
)

_EXTRACT_SCHEMA_BIRTH_CERTIFICATE = (
    "{"
    '"registration_number": "número de matrícula da certidão (novo modelo) ou null", '
    '"name": "nome do registrado ou null", '
    '"birth_date": "data de nascimento no formato AAAA-MM-DD ou null", '
    '"birthplace": "cidade/UF de nascimento ou null", '
    '"mother_name": "nome da mãe ou null", '
    '"father_name": "nome do pai ou null", '
    '"registry": "cartório/cidade do registro ou null", '
    '"name_match": "sim | nao | duvida", '
    '"name_reason": "explicação curta da comparação dos nomes"'
    "}"
)

_EXTRACT_SCHEMA_BLOOD_TYPE = (
    "{"
    '"patient_name": "nome do paciente no documento ou null", '
    '"blood_type": "tipo sanguíneo (A+/A-/B+/B-/AB+/AB-/O+/O-) ou null", '
    '"issuer": "instituição/laboratório que emitiu, string ou null", '
    '"name_match": "sim | nao | duvida", '
    '"name_reason": "explicação curta da comparação dos nomes"'
    "}"
)

_EXTRACT_SCHEMA_MILITARY = (
    "{"
    '"number": "número do documento militar ou null", '
    '"name": "nome do titular ou null", '
    '"situation": "situação militar (reservista/dispensa/alistado/outro) ou null", '
    '"name_match": "sim | nao | duvida", '
    '"name_reason": "explicação curta da comparação dos nomes"'
    "}"
)

EXTRACT_SCHEMAS: dict[str, str] = {
    _T.CERTIFICATE: _EXTRACT_SCHEMA_CERTIFICATE,
    _T.TRANSCRIPT: _EXTRACT_SCHEMA_TRANSCRIPT,
    _T.ADDRESS_PROOF: _EXTRACT_SCHEMA_ADDRESS_PROOF,
    _T.ID_CARD: _EXTRACT_SCHEMA_ID_CARD,
    _T.BIRTH_CERTIFICATE: _EXTRACT_SCHEMA_BIRTH_CERTIFICATE,
    _T.BLOOD_TYPE: _EXTRACT_SCHEMA_BLOOD_TYPE,
    _T.MILITARY: _EXTRACT_SCHEMA_MILITARY,
}

# Campos extraídos por tipo (sem name_match/name_reason).
EXTRACT_FIELDS: dict[str, tuple[str, ...]] = {
    _T.CERTIFICATE: (
        "school_name",
        "student_name",
        "grade",
        "year",
        "city",
    ),
    _T.TRANSCRIPT: (
        "school_name",
        "student_name",
        "years",
        "city",
    ),
    _T.ADDRESS_PROOF: (
        "holder_name",
        "street",
        "number",
        "complement",
        "neighborhood",
        "city",
        "state",
        "zip",
        "issue_date",
        "utility",
    ),
    _T.ID_CARD: (
        "number",
        "issuing_agency",
        "issue_date",
        "name",
        "birth_date",
        "mother_name",
        "father_name",
        "birthplace",
    ),
    _T.BIRTH_CERTIFICATE: (
        "registration_number",
        "name",
        "birth_date",
        "birthplace",
        "mother_name",
        "father_name",
        "registry",
    ),
    _T.BLOOD_TYPE: (
        "patient_name",
        "blood_type",
        "issuer",
    ),
    _T.MILITARY: (
        "number",
        "name",
        "situation",
    ),
}


# Descrição do tipo de documento para prompts de visão.
def doc_type_hint(doc_type: str) -> str:
    return _DOC_TYPE_HINT.get(
        doc_type, _DOC_DESC.get(doc_type, "o documento solicitado")
    )
