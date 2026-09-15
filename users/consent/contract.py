"""Contrato de adesão versionado no BACKEND (LGPD, lane #6).

Fonte da verdade do texto do contrato (antes hardcoded no front). Cada contrato carrega uma
VERSÃO (str) e o HASH SHA-256 do texto — é o que provamos ter sido aceito no ato da selfie
(a selfie É a assinatura). Bump `version` sempre que o texto mudar; o hash é derivado, nunca
digitado à mão.

Dois contratos: ALUNO (matrícula) e PROMOTOR (adesão do colaborador). Para publicar uma versão
"final", troque o texto e suba a `version`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

# str do topo (spec da lane): versão canônica atual dos contratos.
CONTRACT_VERSION = "2026-07-29"


@dataclass(frozen=True)
class Contract:
    """Um contrato versionado. `hash` = sha256(text), derivado — prova a versão aceita."""

    version: str
    text: str
    # Mesmo contrato, apresentado em cláusulas com título (protótipo: a pessoa lê blocos, não um
    # paredão). `text` continua sendo a fonte do hash — é o que provamos ter sido aceito.
    clauses: tuple[tuple[str, str], ...] = ()

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict:
        """Payload do GET /contract/current: {version, hash, text, clauses}."""
        return {
            "version": self.version,
            "hash": self.hash,
            "text": self.text,
            "clauses": [{"t": t, "d": d} for t, d in self.clauses],
        }


_STUDENT_TEXT = """CONTRATO DE PRESTAÇÃO DE SERVIÇOS EDUCACIONAIS E TRATAMENTO DE DADOS

Pelo presente instrumento, o(a) ALUNO(A) adere ao serviço de preparação e certificação supletiva,
autorizando o tratamento dos seus dados pessoais (inclusive documento de identidade e imagem/selfie
biométrica) para as finalidades de matrícula, identificação e emissão de certificado, nos termos da
Lei nº 13.709/2018 (LGPD).

Ao enviar a selfie, o(a) ALUNO(A) declara ter lido e aceito integralmente este contrato, sendo a
selfie a assinatura eletrônica deste aceite. O aceite é registrado com data, hora, endereço IP e
navegador utilizados.

Versão final a definir — este texto é um placeholder e deve ser substituído pela redação jurídica
oficial antes da produção.
"""


# Cláusulas do contrato do promotor, na redação do protótipo. O `text` assinado é derivado
# daqui — cláusula e texto assinado não podem divergir.
_PROMOTER_CLAUSES: tuple[tuple[str, str], ...] = (
    (
        "Sua parceria com a V7M",
        "Pelo presente instrumento, o(a) PROMOTOR(A) atua como afiliado(a) comercial "
        "independente na captação de alunos, recebendo comissão por matrícula paga.",
    ),
    (
        "Comissões e pagamentos",
        "As comissões são apuradas semanalmente e pagas via Pix na chave cadastrada, "
        "sempre no fechamento de sexta-feira.",
    ),
    (
        "Veracidade e uso de imagem",
        "O(A) PROMOTOR(A) declara que as informações prestadas são verdadeiras e autoriza "
        "o uso da imagem e biometria exclusivamente para identificação.",
    ),
    (
        "Confirmação de identidade",
        "A selfie coletada na próxima etapa confirma a identidade do(a) contratante, com "
        "registro de data, hora e dispositivo.",
    ),
    (
        "Proteção dos seus dados (LGPD)",
        "Este acordo observa a Lei Geral de Proteção de Dados (Lei nº 13.709/2018). Seus "
        "dados são tratados apenas para os fins da parceria. Ao enviar a selfie, o(a) "
        "PROMOTOR(A) declara ter lido e aceito integralmente este acordo, sendo a selfie a "
        "assinatura eletrônica do aceite, registrado com data, hora, IP e navegador. "
        "(Texto provisório — versão final a definir.)",
    ),
)

_PROMOTER_TEXT = (
    "CONTRATO DE ADESÃO DO COLABORADOR (PROMOTOR) E TRATAMENTO DE DADOS\n\n"
    + "\n\n".join(f"{t}\n{d}" for t, d in _PROMOTER_CLAUSES)
)

STUDENT_CONTRACT = Contract(version=CONTRACT_VERSION, text=_STUDENT_TEXT)
PROMOTER_CONTRACT = Contract(
    version=CONTRACT_VERSION, text=_PROMOTER_TEXT, clauses=_PROMOTER_CLAUSES
)
