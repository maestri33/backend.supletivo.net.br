"""Synthetic Brazilian Data & KYC Test Vectors Factory.

Generates mathematically valid / invalid CPFs (Mod11), Brazilian E.164 phone numbers,
valid CEP/Address structures, and synthetic image bytes for KYC testing.
"""
from __future__ import annotations

import io
import random
from typing import Literal
from PIL import Image, ImageDraw


class BrazilianDataFactory:
    """Deterministic & Random Brazilian PII Generator for Testing."""

    VALID_DDDS = [
        "11", "12", "13", "14", "15", "16", "17", "18", "19",  # SP
        "21", "22", "24",                                      # RJ
        "27", "28",                                            # ES
        "31", "32", "33", "34", "35", "37", "38",              # MG
        "41", "42", "43", "44", "45", "46",                    # PR
        "47", "48", "49",                                      # SC
        "51", "53", "54", "55",                                # RS
        "61",                                                  # DF
        "62", "64",                                            # GO
        "63",                                                  # TO
        "65", "66",                                            # MT
        "67",                                                  # MS
        "71", "73", "74", "75", "77",                          # BA
        "79",                                                  # SE
        "81", "87",                                            # PE
        "82",                                                  # AL
        "83",                                                  # PB
        "84",                                                  # RN
        "85", "88",                                            # CE
        "86", "89",                                            # PI
        "91", "93", "94",                                      # PA
        "92", "97",                                            # AM
        "95",                                                  # RR
        "96",                                                  # AP
        "98", "99",                                            # MA
    ]

    @staticmethod
    def generate_cpf(formatted: bool = False, valid: bool = True) -> str:
        """Gera um CPF válido (ou intencionalmente inválido) via algoritmo Mod11."""
        if not valid:
            # Inválido: sequência repetida ou dígitos errados
            invalid_seed = str(random.randint(1, 9)) * 11
            return (
                f"{invalid_seed[:3]}.{invalid_seed[3:6]}.{invalid_seed[6:9]}-{invalid_seed[9:]}"
                if formatted
                else invalid_seed
            )

        digits = [random.randint(0, 9) for _ in range(9)]
        
        # Evita 111111111, 222222222 etc
        if len(set(digits)) == 1:
            digits[0] = (digits[0] + 1) % 10

        # Primeiro dígito verificador
        s1 = sum(d * (10 - i) for i, d in enumerate(digits))
        r1 = (s1 * 10) % 11
        d1 = 0 if r1 == 10 else r1
        digits.append(d1)

        # Segundo dígito verificador
        s2 = sum(d * (11 - i) for i, d in enumerate(digits))
        r2 = (s2 * 10) % 11
        d2 = 0 if r2 == 10 else r2
        digits.append(d2)

        raw = "".join(map(str, digits))
        if formatted:
            return f"{raw[:3]}.{raw[3:6]}.{raw[6:9]}-{raw[9:]}"
        return raw

    @classmethod
    def generate_phone(cls, ddd: str | None = None) -> str:
        """Gera telefone celular brasileiro válido no formato E.164 (ex: 5541998765432)."""
        chosen_ddd = ddd if ddd in cls.VALID_DDDS else random.choice(cls.VALID_DDDS)
        suffix = random.randint(10000000, 99999999)
        return f"55{chosen_ddd}9{suffix}"

    @staticmethod
    def generate_address() -> dict[str, str]:
        """Gera dados de endereço sintéticos coerentes com o formato ViaCEP."""
        ceps = [
            {"cep": "80010-000", "logradouro": "Praça Tiradentes", "bairro": "Centro", "cidade": "Curitiba", "uf": "PR"},
            {"cep": "01310-100", "logradouro": "Avenida Paulista", "bairro": "Bela Vista", "cidade": "São Paulo", "uf": "SP"},
            {"cep": "20040-002", "logradouro": "Rua Primeiro de Março", "bairro": "Centro", "cidade": "Rio de Janeiro", "uf": "RJ"},
            {"cep": "30130-000", "logradouro": "Praça Sete de Setembro", "bairro": "Centro", "cidade": "Belo Horizonte", "uf": "MG"},
        ]
        chosen = random.choice(ceps).copy()
        chosen["numero"] = str(random.randint(10, 2500))
        chosen["complemento"] = random.choice(["Apto 101", "Bloco B", "Sala 3", ""])
        return chosen

    @staticmethod
    def generate_synthetic_image(
        kind: Literal["rg_front", "rg_back", "selfie"] = "selfie",
        width: int = 600,
        height: int = 400,
    ) -> bytes:
        """Cria imagem sintética em PNG para testes de KYC e validação de upload."""
        bg_colors = {
            "rg_front": (230, 240, 230),  # Verde claro padrão RG
            "rg_back": (220, 235, 220),
            "selfie": (245, 245, 245),
        }
        bg = bg_colors.get(kind, (240, 240, 240))
        img = Image.new("RGB", (width, height), color=bg)
        draw = ImageDraw.Draw(img)

        # Desenha moldura e texto indicativo
        draw.rectangle([(10, 10), (width - 10, height - 10)], outline=(100, 100, 100), width=2)
        draw.text((20, 20), f"SYNTHETIC VECTOR: {kind.upper()}", fill=(30, 30, 30))

        if kind == "selfie":
            # Desenha um oval representando o rosto
            draw.ellipse([(width // 3, height // 4), (2 * width // 3, 3 * height // 4)], outline=(50, 50, 50), width=3)
        elif "rg" in kind:
            # Desenha linhas simulando campos do documento
            for y in range(80, height - 40, 35):
                draw.line([(30, y), (width - 30, y)], fill=(180, 180, 180), width=1)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
