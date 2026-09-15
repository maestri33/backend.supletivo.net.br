"""Superfície pública in-process do `hub` (CONVENTION §3): o que os grupos `staff`/`leadership`
chamam. Sem regra de negócio no router — ela mora aqui.

Cria/lista polos, designa coordenador (um promotor — spec hub: "coordenador (external_id)"), e
resolve o **hub padrão** (fallback de captação). A marca é validada contra o catálogo do `.env`
(`hub.config`); o coordenador exige a role `promoter` ativa e ganha a role `coordinator`.
"""

from __future__ import annotations

import structlog
from django.db import transaction

from hub import config
from hub.models import Hub
from users.auth.models import User
from users.address import interface as address_iface
from users.roles import interface as roles

logger = structlog.get_logger()


class HubError(Exception):
    """Erro de borda do hub (marca inválida, coordenador não-promotor, polo inexistente, ...)."""


def _coordinator_by_external_id(external_id: str) -> User:
    """Resolve o User do coordenador por external_id.

    Regra: precisa ser PROMOTOR ativo (spec hub/coordinator) — É A REGRA NORMAL.
    EXCEÇÃO (hierarquia de resgate user→coord→staff, Victor 2026-06-17): o **staff**
    (`is_superuser`) pode ser coordenador SEM ser promotor. Por quê: quando o coordenador
    de um polo trava e não há promotor ativo pra herdar, o staff é o último recurso —
    se exigisse promoter, o polo ficaria irresgatável. Staff = supremo resgate.
    """
    user = User.objects.filter(external_id=external_id).first()
    if user is None:
        raise HubError("coordinator_not_found")
    if user.is_superuser:
        return user  # staff destrava qualquer polo (último recurso da hierarquia de resgate)
    if "promoter" not in roles.active_roles(user):
        raise HubError("coordinator_not_promoter")
    return user


def _ensure_coordinator_role(user: User) -> None:
    """Garante a role `coordinator` ativa no user (idempotente).

    Caminho normal: `assign('coordinator')` valida o catálogo (exige promoter ativo) e bump
    do token_version. **EXCEÇÃO (Victor 2026-06-17):** se o user é STAFF (`is_superuser`),
    usa `grant()` direto — pula a regra do catálogo (staff é o último resgate, não precisa
    ser promotor) e NÃO bump o token (staff não toma OTP ao destravar polo).

    Troca de role → notifica o novo coordenador (Victor: toda troca de role avisa os envolvidos)."""
    if "coordinator" in roles.active_roles(user):
        return
    if user.is_superuser:
        roles.grant(
            user, "coordinator"
        )  # pula o catálogo + sem bump (overlay de resgate)
    else:
        roles.assign(user, "coordinator")
    _notify_coordinator_assigned(user)


def _notify_coordinator_assigned(user: User) -> None:
    """Avisa o usuário que acabou de virar coordenador de um polo (best-effort, §12).

    wave-2: send_event lê teor/canais/is_tts do Template no DB."""
    from notify.interface.events import send_event
    from users.profiles import interface as profiles

    p = profiles.get(user)
    try:
        send_event(
            "hub.coordinator_assigned",
            profile=p,
            idempotency_key=f"hub_coord_assigned_{user.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("hub.notify_coordinator_failed", error=str(exc))


def create_hub(
    *,
    brand: str,
    coordinator_external_id: str | None = None,
    address_id: int | None = None,
    cep: str | None = None,
    street: str | None = None,
    number: str | None = None,
    complement: str | None = None,
    neighborhood: str | None = None,
    city: str | None = None,
    state: str | None = None,
    is_default: bool = False,
) -> Hub:
    """Cria um polo: valida marca contra catálogo, exige coordenador promotor e vincula endereço."""
    if not brand or not config.is_valid_brand(brand):
        raise HubError(f"invalid_brand:{brand}")

    if not coordinator_external_id:
        raise HubError("coordinator_required")

    coordinator = _coordinator_by_external_id(coordinator_external_id)

    with transaction.atomic():
        # Resolução do Address
        address = None
        if address_id:
            from users.address.models import Address
            address = Address.objects.filter(pk=address_id).first()
            if address is None:
                raise HubError("address_not_found")
        elif cep:
            address = address_iface.create_empty()
            try:
                address_iface.fill_by_cep(address, cep, number=number, complement=complement)
            except Exception:
                # Se ViaCEP falhar ou estiver em teste, grava os campos recebidos
                address.zipcode = str(cep).replace("-", "").strip()
                address.street = street or address.street
                address.number = number or address.number
                address.complement = complement or address.complement
                address.neighborhood = neighborhood or address.neighborhood
                address.city = city or address.city
                address.state = state or address.state
                address.save()
        elif street and city:
            address = address_iface.create_empty()
            address.street = street
            address.number = number
            address.complement = complement
            address.neighborhood = neighborhood
            address.city = city
            address.state = state
            address.save()
        else:
            # Cria endereço base vazio se nada for informado para não quebrar compatibilidade
            address = address_iface.create_empty()

        hub = Hub.objects.create(
            address=address,
            brand=brand,
            coordinator=coordinator,
            is_default=is_default,
        )
        if coordinator is not None:
            _ensure_coordinator_role(coordinator)

    logger.info(
        "hub.created",
        external_id=str(hub.external_id),
        brand=brand,
        has_coordinator=coordinator is not None,
        address_id=address.pk if address else None,
    )
    return hub



def list_hubs() -> list[Hub]:
    """Todos os polos (mais antigos primeiro)."""
    return list(
        Hub.objects.select_related("coordinator", "address").order_by("created_at")
    )


def get_by_external_id(external_id: str) -> Hub | None:
    return (
        Hub.objects.select_related("coordinator", "address")
        .filter(external_id=external_id)
        .first()
    )


def get_default() -> Hub | None:
    """O polo padrão (fallback de captação: candidato sem `ref` cai nele)."""
    return Hub.objects.filter(is_default=True).select_related("coordinator").first()


def default_coordinator_external_id() -> str | None:
    """external_id do coordenador do hub padrão (fallback de captação). None se não há padrão/coordenador."""
    hub = get_default()
    if hub is None or hub.coordinator is None:
        return None
    return str(hub.coordinator.external_id)


def hub_of(user) -> Hub | None:
    """O polo de um promotor (herança do plano §6-lead-funil): a responsabilidade passa pro HUB do
    promotor que indicou quando o lead vira matrícula (Victor 2026-06-04).

    Preferência (corrigido 2026-06-05 — auditoria): o hub a que o promotor **PERTENCE** (`Promoter.hub`);
    senão o hub que ele **coordena**; senão o **padrão**. Antes resolvia só por coordenação → promotor
    comum (não-coordenador) caía no padrão e a comissão da matrícula/veteran ia pro polo ERRADO. Como a
    conta-mãe tem `Promoter.hub` = hub padrão, o caso atual não muda; o promotor comum (Fatia 2) já fica certo.
    """
    # Lê o model, não o `promoter.service`: o service importa `hub.interface` de volta (auto-matrícula
    # do bolsista) e fechava ciclo. `get_for_user` era exatamente esta query.
    from users.roles.promoter.models import Promoter

    promoter = Promoter.objects.filter(user=user).select_related("hub").first()
    if promoter is not None:
        return promoter.hub
    coordinated = (
        Hub.objects.select_related("coordinator")
        .filter(coordinator=user)
        .order_by("created_at")
        .first()
    )
    return coordinated or get_default()


def resolve_capture_hub(ref: str | None) -> tuple[Hub | None, str]:
    """Resolve o POLO de captação de um candidato a partir do `ref` da landing — TOLERANTE (Victor
    2026-06-23). Nunca bloqueia o cadastro nem estoura por `ref` ruim: sempre devolve um polo COM
    coordenador (pra fila L2 do coordenador poder encher) ou cai no padrão, com o motivo pra log.

    `ref` aceita external_id de POLO **ou** de PROMOTOR (espelha o funil do lead, que usa
    `?ref=promotor`). Devolve `(hub, reason)`; `hub=None` só se nem o polo padrão existir (seed_defaults
    não rodou). Lookups são à prova de `ref` malformado (não-UUID não pode derrubar a porta de entrada).
    """
    from django.core.exceptions import ValidationError

    ref = (ref or "").strip()
    if not ref:
        return get_default(), "no_ref_default"

    # 1) ref como POLO (lookup seguro: ref malformado vira "não achou", não 500).
    try:
        hub = get_by_external_id(ref)
    except (ValueError, ValidationError):
        hub = None
    if hub is not None:
        if hub.coordinator_id is not None:
            return hub, "hub"
        # polo sem coordenador nunca aprovaria o candidato → manda pro padrão e avisa.
        return get_default(), "hub_no_coordinator_default"

    # 2) ref como PROMOTOR (external_id de User) → hub_of (Promoter.hub → coordenado → padrão).
    from users.auth.models import User

    try:
        user = User.objects.filter(external_id=ref, is_active=True).first()
    except (ValueError, ValidationError):
        user = None
    if user is not None:
        promoter_hub = hub_of(user)
        if promoter_hub is not None and promoter_hub.coordinator_id is not None:
            return promoter_hub, "promoter_ref"
        return get_default(), "promoter_hub_no_coordinator_default"

    # 3) ref não resolveu (link velho / typo) → padrão, sem perder o candidato (staff vê pelo log).
    return get_default(), "ref_unresolved_default"


def set_coordinator(*, hub_external_id: str, coordinator_external_id: str) -> Hub:
    """Designa/troca o coordenador do polo (um promotor); garante a role `coordinator` nele."""
    hub = get_by_external_id(hub_external_id)
    if hub is None:
        raise HubError("hub_not_found")
    coordinator = _coordinator_by_external_id(coordinator_external_id)
    with transaction.atomic():
        hub.coordinator = coordinator
        hub.save(update_fields=["coordinator", "updated_at"])
        _ensure_coordinator_role(coordinator)
    logger.info(
        "hub.coordinator_set",
        external_id=str(hub.external_id),
        coordinator=coordinator_external_id,
    )
    return hub


def set_default(external_id: str) -> Hub:
    """Marca o polo como PADRÃO (fallback de captação; único — desmarca os outros, atômico)."""
    hub = get_by_external_id(external_id)
    if hub is None:
        raise HubError("hub_not_found")
    with transaction.atomic():
        Hub.objects.filter(is_default=True).exclude(pk=hub.pk).update(is_default=False)
        if not hub.is_default:
            hub.is_default = True
            hub.save(update_fields=["is_default", "updated_at"])
    logger.info("hub.set_default", external_id=external_id)
    return hub


def set_address(*, hub_external_id: str, cep: str, number=None, complement=None) -> Hub:
    """Preenche o endereço do polo pelo CEP (ViaCEP). O polo nasce com Address vazio (`create_hub`)."""
    hub = get_by_external_id(hub_external_id)
    if hub is None:
        raise HubError("hub_not_found")
    address_iface.fill_by_cep(hub.address, cep, number=number, complement=complement)
    logger.info("hub.address_set", external_id=hub_external_id, cep=cep)
    return hub


def coordinated_by(user):
    """O hub que `user` COORDENA de fato (FK `Hub.coordinator`) — ou None.

    Diferente do `hub_of` (que resolve o polo de um PROMOTOR com fallback pro padrão): aqui é o
    gate duro do coordenador (plan/14) — sem hub coordenado, não há login de coordenador."""
    return Hub.objects.filter(coordinator=user).order_by("created_at").first()
