"""Par de chaves RSA pra assinatura dos JWT (porte do legado `key_service`+`_ensure_keys`).

Gera um par RSA 2048 (privada PKCS8 PEM, pública SPKI PEM, sem criptografia — ambiente DMZ
controlado) no 1º uso, se os arquivos não existirem, nos paths do `.env`
(`JWT_PRIVATE_KEY_PATH`/`JWT_PUBLIC_KEY_PATH`, sob `keys/` gitignored). A privada NUNCA vai pro git.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings

logger = structlog.get_logger()


def _generate_rsa_key_pair(key_size: int = 2048) -> tuple[str, str]:
    """Gera (privada_pem PKCS8, pública_pem SPKI). 2048 = mínimo NIST p/ tokens curtos."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
        backend=default_backend(),
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


def read_or_create_pair(priv_path, pub_path) -> tuple[str, str]:
    """Lê o par PEM (gera se faltar) a partir de paths EXPLÍCITOS ou env vars.

    Prioriza variáveis de ambiente JWT_PRIVATE_KEY_PEM e JWT_PUBLIC_KEY_PEM para
    garantir operação stateless e imutável em contêineres efêmeros (Azure/Docker).
    """
    import os

    env_priv = os.environ.get("JWT_PRIVATE_KEY_PEM")
    env_pub = os.environ.get("JWT_PUBLIC_KEY_PEM")
    if env_priv and env_pub:
        clean_priv = env_priv.replace("\\n", "\n").strip() + "\n"
        clean_pub = env_pub.replace("\\n", "\n").strip() + "\n"
        return clean_priv, clean_pub

    priv_path, pub_path = Path(priv_path), Path(pub_path)
    if not (priv_path.exists() and pub_path.exists()):
        priv_path.parent.mkdir(parents=True, exist_ok=True)
        pub_path.parent.mkdir(parents=True, exist_ok=True)
        priv_pem, pub_pem = _generate_rsa_key_pair()
        priv_path.write_text(priv_pem)
        pub_path.write_text(pub_pem)
        # Permissão restrita na privada (best-effort; em alguns FS não aplica).
        try:
            priv_path.chmod(0o600)
        except OSError:
            pass
        logger.info("jwt.keys_generated", priv=str(priv_path), pub=str(pub_path))
    return priv_path.read_text(), pub_path.read_text()


def ensure_keys() -> None:
    """Gera o par se faltar (idempotente). Usa os paths do `.env` via settings."""
    read_or_create_pair(settings.JWT_PRIVATE_KEY_PATH, settings.JWT_PUBLIC_KEY_PATH)
