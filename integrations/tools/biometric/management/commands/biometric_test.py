"""Face-match REAL entre duas imagens (documento × selfie) — calibração e prova do Portão 3.

Uso: python manage.py biometric_test <doc.jpg> <selfie.jpg>
Imprime {match, score, threshold, status} e grava no ledger `core.ValidationCheck`. Rode com um par
da MESMA pessoa (score alto) e de pessoas DIFERENTES (score baixo) pra calibrar os cortes do .env.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from core.validation import record_check


class Command(BaseCommand):
    help = "Compara duas imagens (documento × selfie) e imprime o score/veredito do face-match."

    def add_arguments(self, parser):
        parser.add_argument(
            "document_image", help="caminho da imagem do documento (com o rosto)"
        )
        parser.add_argument("selfie_image", help="caminho da selfie")

    def handle(self, *args, **options):
        from integrations.tools.biometric import service as biometric
        from integrations.tools.biometric.exceptions import BiometricError

        doc = options["document_image"]
        selfie = options["selfie_image"]
        try:
            result = biometric.compare_images(doc, selfie)
        except BiometricError as exc:
            record_check("biometric", "face_match", False, mode="real", detail=str(exc))
            raise CommandError(f"face-match falhou: {exc}") from exc

        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        flag = "MATCH" if result["match"] else result["status"].upper()
        self.stdout.write(
            self.style.SUCCESS(f"=> {flag} (score={result['score']:.4f})")
        )
        record_check(
            "biometric",
            "face_match",
            result["match"],
            mode="real",
            detail=f"score={result['score']:.4f} status={result['status']}",
        )
