"""Interface pública do integrations.tools.biometric (consumo IN-PROCESS pelos funis candidate/enrollment).

Duas operações de negócio:
- `enroll_face(...)`   → detecta o rosto, gera o embedding e SALVA `FaceBiometric` ligado ao user.
- `verify_identity(...)` → faz o enroll da selfie + compara com o template do DOCUMENTO + grava
  `FaceVerification` (auditoria) + devolve o veredito 3-estados.

Veredito espelha a régua que já existe (`users.roles._selfie.SelfieStatus`), mas as constantes vivem AQUI
(strings iguais) pra a biometria NÃO depender de `users` (camada de cima). Banda dos cortes = `.env`.

Fail-safe: modelo fora / sem rosto / sem template de documento → `review` (= bloqueio; o coordenador
decide). Nada é descartado — toda passada grava `FaceVerification` (rastreabilidade, pedido do Victor).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog
from django.conf import settings

from . import face_match
from .exceptions import BiometricError, ModelUnavailable, NoFaceDetected
from .models import FaceBiometric, FaceVerification

logger = structlog.get_logger()

PROVIDER = "insightface"

# Vocabulário 3-estados (iguais aos valores de users.roles._selfie.SelfieStatus, sem importar de lá).
APPROVED = "approved"
REJECTED = "rejected"
REVIEW = "review"

Source = FaceBiometric.Source


@dataclass(frozen=True)
class FaceMatchResult:
    """Resultado do face-match. `match` == (status == approved)."""

    match: bool
    score: float | None
    threshold: float
    provider: str
    status: str  # approved | rejected | review
    reason: str
    liveness: dict


def classify(score: float) -> tuple[str, bool]:
    """(status, approved) pela banda config do `.env`. >=match → approved; >=review → review; senão reject."""
    match_t = settings.BIOMETRIC_MATCH_THRESHOLD
    review_t = settings.BIOMETRIC_REVIEW_THRESHOLD
    if score >= match_t:
        return APPROVED, True
    if score >= review_t:
        return REVIEW, False
    return REJECTED, False


def _rel(path: str) -> str:
    """Caminho relativo ao MEDIA_ROOT quando possível (tidiness); senão o caminho cru."""
    try:
        return str(
            Path(path).resolve().relative_to(Path(settings.MEDIA_ROOT).resolve())
        )
    except ValueError:
        return str(path)


def enroll_face(*, user, image_path: str, source: str, caller: str) -> FaceBiometric:
    """Detecta o rosto, gera o embedding e SALVA o template ligado ao user. Sem rosto → NoFaceDetected."""
    emb, meta = face_match.embed(
        image_path
    )  # NoFaceDetected / ModelUnavailable sobem pro caller
    bio = FaceBiometric.objects.create(
        user=user,
        source=source,
        image_path=_rel(image_path),
        embedding=emb,
        det_score=meta.get("det_score"),
        provider=PROVIDER,
        metadata={**meta, "caller": caller},
    )
    logger.info(
        "biometric.enrolled",
        user=str(user.external_id),
        source=source,
        det_score=meta.get("det_score"),
    )
    return bio


def try_enroll_document(
    *, user, slot: str, image_path: str, caller: str
) -> FaceBiometric | None:
    """BEST-EFFORT: se o slot for a FRENTE do RG/CNH, salva a biometria do documento. Falha NÃO quebra o
    upload (RG com rosto ruim cai em `review` na hora da selfie). Desligado se BIOMETRIC_ENABLED=False."""
    # frente do RG/CNH (rosto visível) — `_full` = RG inteiro numa imagem (a frente está nela, plan/12)
    if not str(slot).endswith(("_front", "_full")):
        return None
    if not getattr(settings, "BIOMETRIC_ENABLED", True):
        return None
    try:
        return enroll_face(
            user=user, image_path=image_path, source=Source.DOCUMENT, caller=caller
        )
    except BiometricError as exc:
        logger.warning(
            "biometric.document_enroll_skipped",
            caller=caller,
            slot=slot,
            error=str(exc),
        )
        return None
    except Exception as exc:  # noqa: BLE001 — biometria é apoio; jamais bloquear o upload do documento
        logger.warning(
            "biometric.document_enroll_error", caller=caller, slot=slot, error=str(exc)
        )
        return None


def _record(
    *, user, caller, status, approved, score, reference, probe, liveness, reason, meta
) -> FaceMatchResult:
    """Grava o evento de auditoria e devolve o resultado (uma porta de saída só → nada descartado)."""
    FaceVerification.objects.create(
        user=user,
        caller=caller,
        reference=reference,
        probe=probe,
        score=score,
        threshold=settings.BIOMETRIC_MATCH_THRESHOLD,
        approved=approved,
        status=status,
        provider=PROVIDER,
        liveness=liveness,
        metadata=meta,
    )
    return FaceMatchResult(
        match=approved,
        score=score,
        threshold=settings.BIOMETRIC_MATCH_THRESHOLD,
        provider=PROVIDER,
        status=status,
        reason=reason,
        liveness=liveness,
    )


def verify_identity(*, user, selfie_image_path: str, caller: str) -> FaceMatchResult:
    """Compara a SELFIE com o template do DOCUMENTO do user. Salva a selfie (expandir a biometria) +
    grava `FaceVerification`. Modelo fora / sem rosto / sem documento → `review` (= bloqueio).

    Aqui NÃO se decide prova de vida: o veredito de liveness é da IA de visão (`users.roles._selfie`),
    combinado no funil (`add_face_match`). Este método só faz o face-match; `liveness` abaixo é apenas
    o marcador de auditoria de ONDE a prova de vida foi decidida (nunca finge um `passed=True`)."""
    from .liveness import liveness_source

    liveness = liveness_source()

    # 1. enroll da selfie (rosto + embedding). Modelo fora ou sem rosto → review (bloqueio seguro).
    try:
        emb, meta = face_match.embed(selfie_image_path)
    except ModelUnavailable as exc:
        return _record(
            user=user,
            caller=caller,
            status=REVIEW,
            approved=False,
            score=None,
            reference=None,
            probe=None,
            liveness=liveness,
            reason=f"biometria indisponível — enviado p/ revisão do coordenador: {exc}",
            meta={"error": str(exc), "stage": "model"},
        )
    except NoFaceDetected as exc:
        return _record(
            user=user,
            caller=caller,
            status=REVIEW,
            approved=False,
            score=None,
            reference=None,
            probe=None,
            liveness=liveness,
            reason=f"nenhum rosto na selfie — revisão do coordenador: {exc}",
            meta={"error": str(exc), "stage": "selfie"},
        )

    probe = FaceBiometric.objects.create(
        user=user,
        source=Source.SELFIE,
        image_path=_rel(selfie_image_path),
        embedding=emb,
        det_score=meta.get("det_score"),
        provider=PROVIDER,
        metadata={**meta, "caller": caller},
    )

    # 2. TODOS os templates do documento (não só o mais recente). RG frente e RG inteiro dão
    # recortes diferentes do mesmo rosto, e um pode estar bem melhor que o outro — comparar só
    # com o último jogava fora a chance boa (Victor 2026-07-28).
    references = list(
        FaceBiometric.objects.filter(user=user, source=Source.DOCUMENT)
        .exclude(embedding=[])
        .order_by("-created_at")
    )
    # A PRIMEIRA selfie aprovada vira âncora de identidade (Victor 2026-07-29): daí em diante
    # toda selfie nova é comparada também com ela, não só com o documento. O documento envelhece
    # (foto de 10 anos atrás); a selfie aprovada é a cara atual conferida.
    ancoras = _selfies_aprovadas(user, exclude_id=probe.id)
    references = references + ancoras
    if not references:
        return _record(
            user=user,
            caller=caller,
            status=REVIEW,
            approved=False,
            score=None,
            reference=None,
            probe=probe,
            liveness=liveness,
            reason="sem biometria do documento p/ comparar — revisão do coordenador",
            meta={**meta, "stage": "reference"},
        )

    # 3. melhor par (probe × cada referência) → banda config. A galeria de selfies acumulada
    # (`selfie_gallery`) entra como probes ADICIONAIS: cada tentativa anterior continua valendo,
    # então a nota do passo é a MELHOR já obtida — é assim que "ir juntando foto" melhora o
    # resultado em vez de recomeçar do zero a cada tentativa.
    # BURACO FECHADO (2026-07-29): a galeria entrava como probe e o "melhor par" podia aprovar
    # a foto NOVA usando a nota de uma ANTIGA — ou seja, a pessoa da vez não precisava bater com
    # ninguém. Acumular tentativas só vale ENQUANTO não há âncora: aí é a mesma pessoa tentando
    # de novo. Com âncora, a foto atual se defende sozinha.
    probes = (
        [probe] if ancoras else [probe, *_selfie_gallery(user, exclude_id=probe.id)]
    )
    best_score, best_ref, best_probe = None, None, None
    for p in probes:
        for ref in references:
            s = face_match.cosine(p.embedding, ref.embedding)
            if best_score is None or s > best_score:
                best_score, best_ref, best_probe = s, ref, p
    score = best_score
    status, approved = classify(score)
    reason = (
        f"cosseno {score:.4f} (match≥{settings.BIOMETRIC_MATCH_THRESHOLD} / "
        f"review≥{settings.BIOMETRIC_REVIEW_THRESHOLD}) — melhor de "
        f"{len(probes)}×{len(references)} pares"
    )
    logger.info(
        "biometric.verified",
        user=str(user.external_id),
        caller=caller,
        score=round(score, 4),
        status=status,
        probes=len(probes),
        references=len(references),
    )
    return _record(
        user=user,
        caller=caller,
        status=status,
        approved=approved,
        score=score,
        reference=best_ref,
        probe=best_probe,
        liveness=liveness,
        meta={**meta, "probes": len(probes), "references": len(references)},
        reason=reason,
    )


# Quantas selfies anteriores entram na comparação. Teto porque cada par é um cosseno e a
# galeria cresce a cada tentativa; 5 cobre o caso real (algumas tentativas) sem virar O(n²) solto.
_GALLERY_LIMIT = 5


def _selfies_aprovadas(user, *, exclude_id: int | None = None) -> list:
    """Selfies deste usuário que já FORAM aprovadas num face-match — as âncoras de identidade.

    Só entra quem passou: uma selfie reprovada ou em revisão não pode virar referência (senão o
    impostor da primeira tentativa vira o gabarito das próximas)."""
    aprovadas = (
        FaceVerification.objects.filter(user=user, approved=True)
        .exclude(probe__isnull=True)
        .values_list("probe_id", flat=True)
    )
    qs = (
        FaceBiometric.objects.filter(
            user=user, source=Source.SELFIE, id__in=list(aprovadas)
        )
        .exclude(embedding=[])
        .order_by("created_at")
    )
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    return list(qs[:_GALLERY_LIMIT])


def _selfie_gallery(user, *, exclude_id: int | None = None) -> list:
    """Selfies JÁ enroladas deste usuário — as tentativas anteriores viram probes extras."""
    qs = (
        FaceBiometric.objects.filter(user=user, source=Source.SELFIE)
        .exclude(embedding=[])
        .order_by("-created_at")
    )
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    return list(qs[:_GALLERY_LIMIT])


def compare_images(document_image_path: str, selfie_image_path: str) -> dict:
    """Comparação DIRETA por caminho (SEM DB) — pro command `biometric_test`/calibração.

    Contrato do pedido do Victor: {match, score, threshold, provider}. (+ status p/ ver a banda.)
    """
    doc_emb, _ = face_match.embed(document_image_path)
    selfie_emb, _ = face_match.embed(selfie_image_path)
    score = face_match.cosine(selfie_emb, doc_emb)
    status, approved = classify(score)
    return {
        "match": approved,
        "score": score,
        "threshold": settings.BIOMETRIC_MATCH_THRESHOLD,
        "provider": PROVIDER,
        "status": status,
    }
