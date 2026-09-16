"""Lógica do lead (funil do aluno, Fatia 6a): captação → checkout → pago.

`create_lead`: reusa o `register` do `auth` (valida CPFHub+WhatsApp+unicidade, cria User+Profile+
Address+Documents+role `lead`+OTP) + `Lead(PENDING)` + linha do `Checkout` com link curto; a cobrança
no GATEWAY (PIX Asaas / Cartão InfinitePay) é criada em task ASYNC com retry (auditoria front
2026-06-11) — ou lazy, no clique do link curto, se a task ainda não terminou.
`mark_paid`: chamado pelo **hook** de pagamento (CONVENTION §7) — marca pago e dispara os efeitos
(comissão do promotor + cria enrollment ligado ao hub HERDADO do promotor + notify). Idempotente.
"""

from __future__ import annotations

import structlog
from django.db import transaction

from hub import interface as hub_iface
from users.auth import service as auth_iface
from users.auth.models import User
from users.exceptions import DomainError
from users.profiles import interface as profiles
from users.roles.lead import config
from users.roles.lead import checkout_links
from users.roles.lead.models import Checkout, Lead, LeadAttribution

logger = structlog.get_logger()

# método da API (Victor: default cartão) → normalizado.
_API_METHODS = {"card": "card", "credit_card": "card", "pix": "pix"}


class LeadError(DomainError):
    """Erro de borda do lead (método inválido, sem promotor padrão, falha ao gerar checkout).

    É `DomainError` (422): o handler central da API converte em JSON `{detail, code, …extra}`."""

    status = 422


def _save_attribution_safely(lead: Lead, attribution: dict, fallback_ref: str | None = None) -> None:
    """Grava LeadAttribution em savepoint com try/except (doutrina de resiliência).

    Falha de escrita de atribuição NUNCA pode quebrar a captação nem o fluxo do usuário.
    """
    if not attribution:
        return
    try:
        with transaction.atomic():
            ref_val = attribution.get("ref") or fallback_ref or ""
            LeadAttribution.objects.update_or_create(
                lead=lead,
                defaults={
                    "ref_raw": str(ref_val)[:64],
                    "utm_source": str(attribution.get("utm_source") or "")[:128],
                    "utm_medium": str(attribution.get("utm_medium") or "")[:128],
                    "utm_campaign": str(attribution.get("utm_campaign") or "")[:128],
                    "utm_term": str(attribution.get("utm_term") or "")[:128],
                    "utm_content": str(attribution.get("utm_content") or "")[:128],
                    "gclid": str(attribution.get("gclid") or "")[:255],
                    "fbclid": str(attribution.get("fbclid") or "")[:255],
                    "fbp": str(attribution.get("fbp") or "")[:64],
                    "fbc": str(attribution.get("fbc") or "")[:255],
                    "client_ip": attribution.get("client_ip") or None,
                    "user_agent": str(attribution.get("user_agent") or "")[:400],
                    "landing_url": str(attribution.get("landing_url") or "")[:500],
                },
            )
    except Exception as exc:
        logger.warning(
            "lead.attribution_save_failed",
            lead=str(lead.external_id),
            error=str(exc),
        )


def create_lead(
    *, cpf: str, phone: str, email: str, payment_method=None, ref=None, attribution=None
) -> dict:
    """Cria o lead: register + Lead(PENDING) + Checkout síncrono. Retorna external_id+status+checkout.

    Mínimo (Victor 2026-06-04): método (default cartão), cpf, phone, email. `ref` = external_id do
    promotor (landing); sem ref → promotor padrão (coordenador do hub padrão).

    **Caminho LEGADO no funil v2** (protótipo 2026-07-18): o funil novo cria a conta no
    `check_or_capture` (telefone) e o checkout no `set_checkout` (passo 6). Mantido para a API.
    """
    method = _API_METHODS.get((payment_method or "card").strip().lower())
    if method is None:
        raise LeadError("invalid_payment_method")

    promoter = _resolve_promoter(ref)

    reg = auth_iface.register(role="lead", phone=phone, cpf=cpf, email=email)
    user = User.objects.get(external_id=reg["external_id"])

    lead = Lead.objects.create(user=user, promoter=promoter, status=Lead.Status.PENDING)
    if attribution:
        _save_attribution_safely(lead, attribution, fallback_ref=ref)
    # Checkout LOCAL (sem rede): o link curto nasce JÁ; o gateway é resolvido em task async com retry
    # (auditoria front 2026-06-11: register <2s e 201 mesmo com o gateway fora). Se o cliente clicar
    # antes do gateway responder, o redirect tenta criar na hora (lazy — checkout_links).
    checkout = _create_checkout_row(lead, method)
    _enqueue_provider_build(checkout)

    logger.info(
        "lead.created",
        external_id=str(lead.external_id),
        method=method,
        promoter=str(promoter.external_id),
    )
    # ── notifies da CRIAÇÃO do lead (Victor: rastrear; teor final ele edita depois) ──
    _notify_captured(
        lead
    )  # evento LEAD CAPTURADO → vai pro LEAD (o aluno que acabou de entrar) — com TTS
    _notify_promoter_new_lead(
        lead
    )  # evento NOVO LEAD NA REDE → vai pro PROMOTOR (o ref que indicou)
    # o LINK DE PAGAMENTO vai pro lead quando o gateway responder (fill_checkout_from_provider).
    return {
        "external_id": str(lead.external_id),
        "user_external_id": str(user.external_id),
        "status": lead.status,
        "checkout": _checkout_dict(checkout),
    }


def _notify_captured(lead: Lead) -> None:
    """Evento **LEAD CAPTURADO** → destinatário: o **LEAD** (aluno que acabou de entrar no sistema).

    Momento especial → WhatsApp **+ voz (TTS)**, voz por gênero. Teor/canais/is_tts vêm do Template
    no DB (`send_event`); `{nome}`/`{nome-completo}` resolvidos do profile. Best-effort (§12)."""
    from notify.interface.events import send_event

    p = profiles.get(lead.user)
    if p is None:
        return
    try:
        send_event(
            "lead.captured",
            profile=p,
            idempotency_key=f"lead_captured_{lead.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "lead.notify_captured_failed",
            external_id=str(lead.external_id),
            error=str(exc),
        )


def _notify_promoter_new_lead(lead: Lead) -> None:
    """Evento **NOVO LEAD NA REDE** → destinatário: o **PROMOTOR** (o ref que indicou o lead).

    Avisa que um lead entrou pela indicação dele. Teor final o Victor edita depois. Best-effort (§12).
    `{name}` = 1º nome do promotor (do profile); `{lead_name}` vem no ctx."""
    from notify.interface.events import send_event

    lead_p = profiles.get(lead.user)
    prom_p = profiles.get(lead.promoter)
    if prom_p is None:
        return
    lead_name = (lead_p.name if lead_p else None) or "Um novo lead"
    try:
        send_event(
            "lead.captured.promoter",
            profile=prom_p,
            ctx={"lead_name": lead_name},
            idempotency_key=f"lead_new_promoter_{lead.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "lead.notify_promoter_new_failed",
            external_id=str(lead.external_id),
            error=str(exc),
        )


def _notify_checkout(lead: Lead, checkout: Checkout) -> None:
    """Envia o LINK de pagamento (curto) ao lead por WhatsApp — o legado fazia, faltava aqui.

    Best-effort (§12). Evento por método: `lead.checkout.pix` (com copia-e-cola) ou `lead.checkout.card`.
    Teor/canais do DB; `{valor}`/`{link}`/`{payload}` no ctx. TTS/wording = decisão do Victor no DB."""
    from notify.interface.events import send_event

    profile = profiles.get(lead.user)
    if profile is None:
        return
    link = checkout_links.short_url(checkout.short_token) or checkout.checkout_url
    amount = f"R${checkout.amount}"
    if checkout.payment_method == Checkout.Method.PIX:
        event = "lead.checkout.pix"
        ctx = {"valor": amount, "link": link, "payload": checkout.qrcode_payload or "-"}
    else:
        event = "lead.checkout.card"
        ctx = {"valor": amount, "link": link}
    try:
        send_event(
            event,
            profile=profile,
            ctx=ctx,
            # por TOKEN (não por lead): trocar a forma de pagamento gera checkout novo → o link
            # novo notifica de novo (funil v2); o mesmo checkout continua notificando UMA vez.
            idempotency_key=f"lead_checkout_{lead.external_id}_{checkout.short_token}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "lead.notify_checkout_failed",
            external_id=str(lead.external_id),
            error=str(exc),
        )


def _resolve_promoter(ref) -> User:
    """`ref` (external_id) → promotor ATIVO; fallback em cascata que NUNCA perde um lead.

    Cascata (Issue #35 — blindagem 2026-09-15):
      1. `ref` válido → promotor ACTIVE direto.
      2. Coordenador do hub PADRÃO (caminho normal do seed_defaults).
      3. Coordenador de QUALQUER hub ativo (resgate se o padrão não existe).
      4. Primeiro superuser ativo (último recurso — staff destrava tudo).
      5. LeadError só se NÃO há nenhum User ativo no sistema inteiro.

    Usa `promoter.validate_ref` (exige `Promoter` com status ACTIVE) em vez de só checar a role: assim um
    promotor SUSPENSO ("não capta nem recebe") não amarra leads nem ganha comissão (auditoria 2026-06-05).
    """
    if ref:
        from users.roles.promoter import service as promoter_iface

        u = promoter_iface.validate_ref(ref)
        if u is not None:
            return u
        # WARNING de propósito (auditoria 2026-07-25, "buraco 3"): indicação DESVIADA pro padrão
        # não pode se esconder em log info — é comissão trocando de dono sem ninguém ver.
        logger.warning("lead.ref_fallback_default", ref=str(ref))

    # Fallback 1: coordenador do hub padrão (caminho normal)
    ext = hub_iface.default_coordinator_external_id()
    if ext:
        u = User.objects.filter(external_id=ext, is_active=True).first()
        if u is not None:
            return u
        logger.warning("lead.default_coordinator_inactive", external_id=str(ext))

    # Fallback 2: coordenador de QUALQUER hub ativo (resgate se padrão não existe/sem coordenador)
    from hub.models import Hub

    hub_with_coord = (
        Hub.objects.filter(coordinator__isnull=False, coordinator__is_active=True)
        .select_related("coordinator")
        .order_by("-is_default", "created_at")
        .first()
    )
    if hub_with_coord is not None:
        logger.warning(
            "lead.fallback_any_hub_coordinator",
            hub=str(hub_with_coord.external_id),
            coordinator=str(hub_with_coord.coordinator.external_id),
        )
        return hub_with_coord.coordinator

    # Fallback 3: primeiro superuser ativo (último recurso — staff destrava tudo)
    staff = User.objects.filter(is_superuser=True, is_active=True).order_by("pk").first()
    if staff is not None:
        logger.warning(
            "lead.fallback_staff_superuser",
            staff=str(staff.external_id),
        )
        return staff

    # Sem ninguém ativo no sistema inteiro — seed_defaults não rodou E não há staff
    raise LeadError("no_default_promoter")


def referral_name(ref) -> str | None:
    """`?ref=` → PRIMEIRO nome do promotor, pro selo "Indicado por …" da tela 1 (funil v2).

    Deliberadamente MAGRO porque é público: só o primeiro nome, nunca sobrenome/contato — o `ref`
    circula em link compartilhável, então este endpoint não pode virar consulta de cadastro.
    Ref inválido/suspenso/travado no treino → None e o front esconde o selo. **NÃO** cai no promotor
    padrão como o `_resolve_promoter`: atribuir a captação por dentro é uma coisa, escrever o nome
    de outra pessoa na tela do lead é outra.
    """
    if not ref:
        return None
    from users.roles.promoter import service as promoter_iface

    user = promoter_iface.validate_ref(ref)
    if user is None:
        return None
    profile = profiles.get(user)
    name = (profile.name or "").strip() if profile else ""
    return name.split()[0] if name else None


def _create_checkout_row(lead: Lead, method: str) -> Checkout:
    """Cria a LINHA do checkout (local, sem rede) com o token do link curto já gerado.

    Os campos do gateway (URL/QR/payment_id) ficam nulos até `fill_checkout_from_provider` —
    chamado pela task async (com retry) ou pelo clique no link curto (lazy)."""
    self_study = lead.self_study  # auto-matrícula de promotor → preço PRÓPRIO
    if method == "pix":
        provider = Checkout.Provider.ASAAS
        amount = config.promoter_price_pix() if self_study else config.price_pix()
        pay_method = Checkout.Method.PIX
    else:
        provider = Checkout.Provider.INFINITEPAY
        amount = config.promoter_price_card() if self_study else config.price_card()
        pay_method = Checkout.Method.CREDIT_CARD
    return Checkout.objects.create(
        lead=lead,
        payment_method=pay_method,
        provider=provider,
        amount=amount,
        short_token=checkout_links.new_token(),
    )


def _enqueue_provider_build(checkout: Checkout) -> None:
    """Agenda a criação no gateway via Django-Q (best-effort: broker é o ORM, mas não quebra o register)."""
    try:
        from core.tasks import async_task

        async_task("users.roles.lead.tasks.build_checkout", checkout.pk)
    except Exception as exc:  # noqa: BLE001 — o clique no link curto cobre (lazy build)
        logger.warning(
            "lead.checkout_enqueue_failed", checkout=checkout.pk, error=str(exc)
        )


def is_checkout_built(checkout: Checkout) -> bool:
    """O checkout JÁ foi construído no gateway? (guard de idempotência do build)

    **Cartão** (InfinitePay): o sinal é a `checkout_url` — o gateway só existe como link.

    **PIX** (QR estático do Asaas): `checkout_url` NÃO serve de sinal. O QR estático não tem
    fatura hospedada, então até a issue #158 o campo ficava `None` e o guard nunca fechava: cada
    clique no link curto tentava recriar o QR com o MESMO `pid` e o Asaas devolvia
    `payment_id_already_exists` → 503 eterno. O sinal honesto do PIX é ter cobrança emitida:
    `provider_payment_id` (o `externalReference` que o webhook casa) ou o `qrcode_payload`."""
    if checkout.payment_method == Checkout.Method.PIX:
        return bool(checkout.provider_payment_id or checkout.qrcode_payload)
    return bool(checkout.checkout_url)


def fill_checkout_from_provider(checkout: Checkout) -> None:
    """Cria a cobrança no GATEWAY e preenche o Checkout (URL/QR/payment_id). FAZ REDE — nunca dentro
    do request do register (task async ou lazy no clique do link curto).

    Idempotente: já preenchido → no-op (ver `is_checkout_built`). Mutex curto no cache evita
    task × clique criarem DUAS cobranças no provider ao mesmo tempo."""
    from django.core.cache import cache

    if is_checkout_built(checkout):
        return
    lock_key = f"checkout_build:{checkout.pk}"
    if not cache.add(lock_key, 1, 30):  # outro builder em andamento
        return
    try:
        checkout.refresh_from_db()
        if is_checkout_built(checkout):
            return
        profile = profiles.get(checkout.lead.user)
        if profile is None:
            raise LeadError("profile_missing")
        if checkout.payment_method == Checkout.Method.PIX:
            _fill_pix(checkout, profile)
        else:
            _fill_card(checkout, profile)
    finally:
        cache.delete(lock_key)
    logger.info(
        "lead.checkout_filled",
        external_id=str(checkout.lead.external_id),
        provider=checkout.provider,
    )
    # agora existe link de verdade → manda o LINK DE PAGAMENTO pro lead (idempotente por key).
    _notify_checkout(checkout.lead, checkout)


def _fill_pix(checkout: Checkout, profile) -> None:
    from integrations.bank.asaas import static_qr as asaas_static_qr
    from integrations.bank.asaas.qr import qr_url_for

    lead = checkout.lead
    # pid = externalReference que o webhook do Asaas casa (mark_paid busca pelo pid GRAVADO na linha).
    # Sufixo do checkout.pk: o lead pode TROCAR a forma de pagamento → cada checkout
    # gera um QR Code novo (o asaas_id é único; reusar colidiria).
    pid = f"lead_{lead.external_id.hex[:12]}_{checkout.pk}"

    # QR Code PIX estático direto — custo menor que fatura gerenciada (/v3/payments).
    # Não exige criação de customer no Asaas, não gera fatura, não cria link hospedado.
    # A conciliação é pelo externalReference (= pid) no webhook PAYMENT_RECEIVED.
    # `create_pix_qr` é IDEMPOTENTE por `payment_id`: um build que já emitiu o QR e morreu depois
    # (ou dois cliques no link curto) REAPROVEITA a linha em vez de estourar (issue #158).
    payment = asaas_static_qr.create_pix_qr(
        amount=checkout.amount,  # valor EXATO do plano — o QR estático carrega o `value` cravado
        description=config.description(),
        payment_id=pid,
    )

    checkout.provider_payment_id = payment.payment_id
    # O QR estático não tem fatura hospedada — o destino é a NOSSA página PIX, que mostra o
    # copia-e-cola + o PNG persistidos aqui. Sem FRONTEND_URL a URL fica nula e a view do link
    # curto renderiza a página mínima do Django (nunca 503).
    checkout.checkout_url = checkout_links.pix_page_url(checkout.short_token)
    checkout.qrcode_payload = payment.qrcode_payload
    checkout.qrcode_image = qr_url_for(payment.payment_id)
    checkout.due_date = None  # QR Code estático não tem vencimento
    checkout.save(
        update_fields=[
            "provider_payment_id",
            "checkout_url",
            "qrcode_payload",
            "qrcode_image",
            "due_date",
            "updated_at",
        ]
    )
    if checkout.checkout_url:
        checkout_links.bind(checkout.short_token, checkout.checkout_url)


def _fill_card(checkout: Checkout, profile) -> None:
    from integrations.bank.infinitepay import checkout as ip_checkout

    # pré-preenche o checkout com os dados que JÁ temos (nome do CPFHub + email + telefone).
    # Schema {name, email, phone_number} no padrão E.164 (+55...) para evitar falso DDI.
    phone = profile.phone or ""
    phone_digits = "".join(c for c in phone if c.isdigit())
    if phone_digits and not phone_digits.startswith("55"):
        phone_digits = f"55{phone_digits}"
    customer = {
        "name": profile.name or "",
        "email": profile.email or "",
        "phone_number": f"+{phone_digits}" if phone_digits else "",
    }
    # redirect_url: pra onde a InfinitePay manda o pagador DEPOIS de pagar (frontend_url).
    row = ip_checkout.create_checkout(
        amount=checkout.amount,
        description=config.description(),
        customer=customer,
        redirect_url=config.frontend_url(),
    )
    checkout.provider_payment_id = str(
        row.external_id
    )  # = order_nsu que o webhook do infinitepay casa
    checkout.checkout_url = row.checkout_url
    checkout.save(update_fields=["provider_payment_id", "checkout_url", "updated_at"])
    checkout_links.bind(checkout.short_token, checkout.checkout_url)


def pix_page_dict(token: str) -> dict | None:
    """Dados da página PIX PRÓPRIA, endereçados pelo `short_token` (PÚBLICO, sem login).

    O lead chega pelo link do WhatsApp — não tem sessão. O token é o mesmo segredo do link curto
    (`secrets.token_urlsafe(9)`), então a superfície é a MESMA que já existia; e o payload é
    deliberadamente MAGRO: valor + copia-e-cola + PNG + pago/não pago. Nada de nome, CPF,
    telefone ou e-mail — a página é compartilhável por natureza (issue #158).

    `None` se o token não existe (a rota devolve 404). Método ≠ PIX → também `None`: cartão tem
    página do gateway, não é assunto desta tela."""
    from integrations.bank.asaas.qr import qr_path_for

    c = Checkout.objects.filter(short_token=token).first()
    if c is None or c.payment_method != Checkout.Method.PIX:
        return None
    image = (
        qr_path_for(c.provider_payment_id) if c.provider_payment_id else None
    ) or c.qrcode_image
    return {
        "amount": str(c.amount),
        "is_paid": c.is_paid,
        "qrcode_payload": c.qrcode_payload,
        "qrcode_image": image,
        "receipt_url": c.receipt_url,
    }


def _checkout_dict(c: Checkout) -> dict:
    return {
        "payment_method": c.payment_method,
        "provider": c.provider,
        "amount": str(c.amount),
        "is_paid": c.is_paid,
        "checkout_url": c.checkout_url,
        "url": c.checkout_url or checkout_links.short_url(c.short_token),
        "short_url": checkout_links.short_url(
            c.short_token
        ),  # link curto p/ mandar por WhatsApp
        "qrcode_payload": c.qrcode_payload,
        "qrcode_image": c.qrcode_image,
        "due_date": c.due_date.isoformat() if c.due_date else None,
    }


# ── funil do lead v2 (protótipo 2026-07-18): telefone → OTP → CPF → e-mail → checkout ──
# A API SE MOLDA AO PROTÓTIPO (DOCUMENTACAO, "martelo batido"): a conta nasce no passo do
# TELEFONE (o /auth/register como criador de lead fica aposentado no funil) e a escolha de
# pagamento vem POR ÚLTIMO — o Lead nasce SEM checkout; o checkout entra (e pode ser TROCADO)
# no passo 6 via `set_checkout`.


def check_or_capture(
    *,
    cpf: str | None = None,
    phone: str | None = None,
    external_id: str | None = None,
    send_otp: bool = True,
    service_authed: bool = False,
    ref: str | None = None,
    attribution: dict | None = None,
) -> dict:
    """`POST clients/auth/check` do funil v2: o check normal E a captura no mesmo passo.

    - Usuário EXISTE → comporta igual ao `auth.check` (OTP + found + roles honestos; o front
      roteia: sem role de cliente → portal da equipe; student/veteran → app do aluno).
    - NÃO existe, veio `phone` e o WhatsApp CONFIRMOU o número → **cria a conta na hora**
      (User+Profile(phone)+role lead+Lead ligado ao promotor do `?ref=`) e dispara o OTP —
      resposta ganha `created: true` + `external_id` (o front segue direto pro OTP).
    - NÃO existe e WhatsApp negou (`whatsapp:false`) ou está fora (`whatsapp:null`) → NÃO cria;
      o front bloqueia/avisa (modais "número inválido"/"não consegui confirmar").

    Rate-limit por IP fica no reverse proxy (mesma régua do check). O WhatsApp é consultado 2×
    no caminho de captura (check + register) — aceito por ora: o register resolve o número
    canônico (variante 9º dígito) e o custo é baixo; unificar é otimização futura."""
    result = auth_iface.check(
        cpf=cpf,
        phone=phone,
        external_id=external_id,
        send_otp=send_otp,
        service_authed=service_authed,
    )
    if result["found"] or not phone or not send_otp:
        if result.get("found") and attribution and result.get("external_id"):
            try:
                user = User.objects.filter(external_id=result["external_id"]).first()
                if user and hasattr(user, "lead") and not hasattr(user.lead, "attribution"):
                    _save_attribution_safely(user.lead, attribution, fallback_ref=ref)
            except Exception as exc:
                logger.warning("lead.attribution_backfill_failed", error=str(exc))
        return {**result, "created": False}
    if result.get("whatsapp") is not True:
        return {**result, "created": False}

    # A captura é best-effort NO ENDPOINT PÚBLICO: se não completar (seed sem promotor padrão,
    # corrida de PHONE_EXISTS), o check degrada honesto pro resultado puro (`created:false`) em
    # vez de 4xx/5xx — o front avisa e o usuário re-tenta. O erro fica alto no log.
    try:
        promoter = _resolve_promoter(ref)
        reg = auth_iface.register(
            role="lead", phone=phone
        )  # cpf/e-mail entram nos passos 3/5
        user = User.objects.get(external_id=reg["external_id"])
        lead = Lead.objects.create(
            user=user, promoter=promoter, status=Lead.Status.PENDING
        )
        if attribution:
            _save_attribution_safely(lead, attribution, fallback_ref=ref)
    except DomainError as exc:
        logger.warning("lead.capture_on_check_failed", code=exc.code, error=exc.detail)
        return {**result, "created": False}
    logger.info(
        "lead.captured_on_check",
        external_id=str(lead.external_id),
        promoter=str(promoter.external_id),
    )
    _notify_captured(lead)
    _notify_promoter_new_lead(lead)
    _enqueue_avatar_fetch(
        user
    )  # foto do zap pro pergaminho (tela 3-4) — async, enfeite
    return {
        "found": False,
        "created": True,
        "external_id": reg["external_id"],
        "otp_sent": reg["otp_sent"],
        "otp_wait": None,
        "whatsapp": True,
        "roles": ["lead"],
        "token": None,
    }


def _enqueue_avatar_fetch(user: User) -> None:
    """Agenda a captura da foto de perfil do WhatsApp (tasks.fetch_whatsapp_avatar).

    Mesmo padrão do `_enqueue_provider_build`: best-effort — broker fora não pode
    derrubar a captura; sem foto o pergaminho usa o monograma e a vida segue."""
    profile = profiles.get(user)
    if profile is None:
        return
    try:
        from core.tasks import async_task

        async_task("users.roles.lead.tasks.fetch_whatsapp_avatar", profile.pk)
    except Exception as exc:  # noqa: BLE001 — enfeite: sem task, fica sem foto
        logger.warning("lead.avatar_enqueue_failed", profile=profile.pk, error=str(exc))


def set_checkout(
    *,
    user_external_id: str,
    payment_method: str | None,
    attribution: dict | None = None,
) -> dict:
    """Passo 6 do funil v2: define (ou TROCA) a forma de pagamento do lead logado — cria o
    checkout na hora e devolve o dict (URL nasce async/lazy, como no register legado).

    Contrato do protótipo (painel "Pagamento já preparado" → "Trocar"): o lead pode trocar a
    forma DEPOIS do checkout criado. Recriar = apagar a linha antiga (o link curto antigo morre
    junto — `checkout_links.resolve` não acha mais o token) + cancelar a cobrança PIX antiga no
    Asaas (best-effort; cartão InfinitePay não tem cancel — o link antigo apenas fica órfão) +
    criar linha nova com token/pid novos.

    Guardas: lead PAGO → 409 `ALREADY_PAID` (não mexe em pagamento concluído). Perfil sem
    cpf/e-mail (pulou passos 3/5) → 409 `PROFILE_INCOMPLETE` + `missing_fields`."""
    from users.exceptions import Conflict, NotFound

    lead = get_for_user_external_id(user_external_id)
    if lead is None:
        raise NotFound("Lead não encontrado.", code="LEAD_NOT_FOUND")
    if attribution:
        _save_attribution_safely(lead, attribution)
    method = _API_METHODS.get((payment_method or "").strip().lower())
    if method is None:
        raise LeadError("invalid_payment_method")
    if lead.status == Lead.Status.PAID:
        raise Conflict("Pagamento já confirmado.", code="ALREADY_PAID")

    profile = profiles.get(lead.user)
    missing = [
        field
        for field, value in (
            ("cpf", profile.cpf if profile else None),
            ("email", profile.email if profile else None),
        )
        if not value
    ]
    if profile is None or missing:
        raise Conflict(
            "Complete a identidade e o e-mail antes do pagamento.",
            code="PROFILE_INCOMPLETE",
            extra={"missing_fields": missing or ["cpf", "email"]},
        )

    old = getattr(lead, "checkout", None)
    if old is not None:
        if old.is_paid:
            raise Conflict("Pagamento já confirmado.", code="ALREADY_PAID")
        _cancel_provider_charge(old)
        checkout_links.unbind(old.short_token)  # o link antigo morre com a linha (não pelo TTL)
        old.delete()
        # refresh: a relação 1-1 fica cacheada no objeto — sem isso o create abaixo colide.
        lead = Lead.objects.get(pk=lead.pk)
        logger.info(
            "lead.checkout_replaced",
            external_id=str(lead.external_id),
            new_method=method,
        )

    checkout = _create_checkout_row(lead, method)
    _enqueue_provider_build(checkout)
    return _checkout_dict(checkout)


def _cancel_provider_charge(checkout: Checkout) -> None:
    """Cancela a cobrança substituída no gateway (best-effort — a troca de método não pode
    travar por instabilidade do provider; a linha local morre de qualquer jeito e o webhook de
    um pagamento tardio no link antigo cai no fallback rastreável do mark_paid)."""
    if not checkout.provider_payment_id:
        return  # gateway nem respondeu ainda — nada a cancelar
    if checkout.provider != Checkout.Provider.ASAAS:
        return  # InfinitePay não expõe cancel de link — o checkout antigo fica órfão
    try:
        from integrations.bank.asaas import charge as asaas_charge
        from integrations.bank.asaas import static_qr as asaas_static_qr
        from integrations.bank.asaas.models import Payment

        # O PIX do lead é QR estático (kind=static_pix_qr), NÃO fatura (kind=charge): mandar pro
        # `cancel_charge` só levantava `not_found` (engolido aqui) e o QR antigo seguia vivo,
        # aceitando pagamento de um checkout que já morreu. Roteia pelo kind da linha.
        if Payment.objects.filter(
            payment_id=checkout.provider_payment_id,
            kind=Payment.Kind.STATIC_PIX_QR,
        ).exists():
            asaas_static_qr.cancel_pix_qr(checkout.provider_payment_id)
        else:
            asaas_charge.cancel_charge(checkout.provider_payment_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "lead.checkout_cancel_failed",
            external_id=str(checkout.lead.external_id),
            error=type(exc).__name__,
        )


# ── self (o próprio cliente vê seu lead: GET /clients/lead/me) ───────────────


def get_for_user_external_id(user_external_id: str) -> Lead | None:
    """O lead do usuário logado (1-1 com o User)."""
    return (
        Lead.objects.filter(user__external_id=user_external_id)
        .select_related("user", "promoter", "checkout")
        .first()
    )


def checkout_url_for(lead: Lead) -> str | None:
    """A URL ÚNICA do lead (link curto): `checkout_links.resolve` redireciona pro gateway se NÃO pago,
    pro recibo se pago. `None` se ainda não há checkout."""
    c = getattr(lead, "checkout", None)
    return checkout_links.short_url(c.short_token) if c else None


def lead_self_dict(lead: Lead) -> dict:
    """TODOS os dados do lead pro próprio cliente (Victor 2026-06-07): pagamento + cliente + promotor.

    Inclui a URL única (✦) que redireciona checkout↔recibo. NÃO é a `lead_to_dict` (visão de hub/staff)."""
    c = getattr(lead, "checkout", None)
    customer = profiles.get(lead.user)
    promoter = profiles.get(lead.promoter)
    checkout = None
    if c is not None:
        checkout = _checkout_dict(c)
        checkout["url"] = checkout.pop("short_url")  # ✦ a URL única (checkout↔recibo)
        checkout["receipt_url"] = c.receipt_url
    return {
        "external_id": str(lead.external_id),
        "status": lead.status,
        "failed_reason": lead.failed_reason,
        "created_at": lead.created_at.isoformat(),
        "customer": {
            "name": customer.name if customer else None,
            "phone": customer.phone if customer else None,
            "email": customer.email if customer else None,
            "cpf": customer.cpf if customer else None,
        },
        "promoter": {
            "external_id": str(lead.promoter.external_id),
            "name": promoter.name if promoter else None,
        },
        "checkout": checkout,
    }


def pricing(ref: str | None = None) -> dict:
    """Preço público de vitrine — É O MESMO que é cobrado (Victor 2026-06-07): PIX (valor cheio) + cartão 12x.

    Lê a MESMA fonte da cobrança (`price_pix`/`price_card`): PIX em reais; cartão do `.env` em centavos → reais.
    Suporta precificação promocional com desconto quando acessado via `ref` de promotor válido.
    """
    from decimal import Decimal

    pix = config.price_pix()
    total = config.price_card()
    installments = config.card_installments()
    installment = (total / installments).quantize(Decimal("0.01"))

    promo_pix = config.promo_price_pix()
    promo_total = config.promo_price_card()
    promo_installment = (promo_total / installments).quantize(Decimal("0.01"))
    anchor_full = config.anchor_full()

    name = referral_name(ref) if ref else None
    has_discount = bool(name)

    return {
        "pix": f"{pix:.2f}",
        "card": {
            "installments": installments,
            "installment": f"{installment:.2f}",
            "total": f"{total:.2f}",
        },
        "promo_pix": f"{promo_pix:.2f}",
        "promo_card": {
            "installments": installments,
            "installment": f"{promo_installment:.2f}",
            "total": f"{promo_total:.2f}",
        },
        "has_discount": has_discount,
        "promoter_name": name,
        "anchor_full": f"{anchor_full:.2f}",
    }


def promoter_pricing() -> dict:
    """Vitrine da auto-matrícula do PROMOTOR (preço próprio; mesma estrutura do `pricing`)."""
    from decimal import Decimal

    pix = config.promoter_price_pix()
    total = config.promoter_price_card()
    installments = config.card_installments()
    installment = (total / installments).quantize(Decimal("0.01"))
    return {
        "pix": f"{pix:.2f}",
        "card": {
            "installments": installments,
            "installment": f"{installment:.2f}",
            "total": f"{total:.2f}",
        },
    }


def create_self_study_lead(*, user, payment_method=None) -> dict:
    """Auto-matrícula de um PROMOTOR que quer estudar (Victor 2026-06-16): Lead(self_study) + Checkout no
    PREÇO DE PROMOTOR, SEM comissão a ninguém. NÃO troca role agora (a role lead/enrollment entra no
    PAGAMENTO) — o promotor segue logado no app dele até pagar. `user` já existe (promotor ATIVO)."""
    from users.roles.promoter import service as promoter_iface
    from users.roles.promoter.models import Promoter
    from users.roles.training import service as training_iface

    method = _API_METHODS.get((payment_method or "card").strip().lower())
    if method is None:
        raise LeadError("invalid_payment_method")

    promoter = promoter_iface.get_for_user(user)
    if promoter is None or promoter.status != Promoter.Status.ACTIVE:
        raise LeadError("not_active_promoter")
    if training_iface.is_locked(user):
        raise LeadError("promoter_locked")  # travado no treino → ainda não estuda
    if Lead.objects.filter(user=user).exists():
        raise LeadError("lead_already_exists")

    lead = Lead.objects.create(
        user=user, promoter=user, self_study=True, status=Lead.Status.PENDING
    )
    checkout = _create_checkout_row(lead, method)
    _enqueue_provider_build(checkout)
    _notify_captured(
        lead
    )  # boas-vindas ao próprio promotor (sem "novo lead" a ninguém)
    logger.info("lead.self_study_created", external_id=str(lead.external_id))
    return {
        "external_id": str(lead.external_id),
        "user_external_id": str(user.external_id),
        "status": lead.status,
        "checkout": _checkout_dict(checkout),
    }


# ── pagamento (chamado pelo hook do webhook, CONVENTION §7) ─────────────────


def mark_paid(*, provider: str, provider_payment_id: str, receipt_url=None) -> bool:
    """Casa o Checkout do lead por (provider, provider_payment_id). Se for nosso → marca pago + efeitos.

    `receipt_url` (do webhook) é guardado no Checkout e vai pro aluno na notify de pago. Idempotente
    (lead já PAID → no-op). True se consumiu (era checkout de lead), senão False (o webhook cai no
    fallback rastreável — pode ser cobrança de `fees`, não nossa).
    """
    checkout = (
        Checkout.objects.select_related("lead", "lead__user", "lead__promoter")
        .filter(provider=provider, provider_payment_id=provider_payment_id)
        .first()
    )
    if checkout is None:
        return False

    lead = checkout.lead
    if lead.status == Lead.Status.PAID:
        return True  # idempotente (webhook re-tentou)

    with transaction.atomic():
        fields = ["is_paid", "updated_at"]
        checkout.is_paid = True
        if receipt_url:
            checkout.receipt_url = receipt_url
            fields.insert(1, "receipt_url")
        checkout.save(update_fields=fields)
        lead.status = Lead.Status.PAID
        lead.save(update_fields=["status", "updated_at"])
        hub = _apply_effects(lead)
        if not lead.self_study:
            try:
                from core.tasks import async_task

                transaction.on_commit(
                    lambda: async_task(
                        "integrations.analytics.tasks.send_purchase",
                        str(lead.external_id),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "lead.analytics_enqueue_failed",
                    lead=str(lead.external_id),
                    error=str(exc),
                )

    _notify_paid(
        lead, hub, checkout
    )  # fora da transação: best-effort, não desfaz comissão/enrollment
    logger.info("lead.paid", external_id=str(lead.external_id), provider=provider)
    return True


def _apply_effects(lead: Lead):
    """Dentro da transação. Lead normal: comissão do promotor + enrollment no hub herdado. Auto-matrícula
    de promotor (`self_study`): hub é o DELE (Promoter.hub), **SEM comissão a ninguém** (Victor 2026-06-16).
    Retorna o hub."""
    from finance.interface import commissions
    from finance.models import Commission
    from users.roles import interface as roles
    from users.roles.enrollment import service as enrollment_iface

    if lead.self_study:
        hub = hub_iface.hub_of(lead.user)  # o próprio polo do promotor
        if hub is None:
            raise LeadError("no_hub_for_promoter")
        # promotor ganha a role lead aqui (não no início — assim ele segue logado no app dele até pagar);
        # `create_from_lead` promove lead→enrollment em seguida. NÃO credita comissão.
        if "lead" not in roles.active_roles(lead.user):
            roles.assign(lead.user, "lead")
        enrollment_iface.create_from_lead(
            user=lead.user, promoter=lead.user, hub=hub, self_study=True
        )
        return hub

    # G7: promotor SUSPENSO não recebe comissão de lead que paga após a suspensão (Promoter.suspend
    # documenta "não capta nem recebe"). O cliente ainda vira matrícula — só a comissão é pulada.
    from users.roles.promoter.models import Promoter

    suspenso = Promoter.objects.filter(
        user=lead.promoter, status=Promoter.Status.SUSPENDED
    ).exists()
    if suspenso:
        logger.info(
            "lead.commission_skipped_promoter_suspended",
            promoter=str(lead.promoter.external_id),
            lead=str(lead.external_id),
        )
    else:
        commissions.credit_commission(
            payee=lead.promoter,
            payee_role=Commission.Role.PROMOTER,
            source_type=Commission.Source.LEAD,
            source_external_id=lead.external_id,
        )
    hub = hub_iface.hub_of(lead.promoter)
    if hub is None:
        raise LeadError("no_hub_for_promoter")
    enrollment_iface.create_from_lead(user=lead.user, promoter=lead.promoter, hub=hub)
    # F4: este lead pago conta como indicação — se o promotor é pré-matriculado e bateu 3, entra
    # sozinho como bolsista (SEM pagamento). G4/#21: em SAVEPOINT — a auto-matrícula do PROMOTOR é
    # efeito secundário; se ela falha, reverte só a si mesma e o pagamento do CLIENTE (comissão +
    # matrícula, já commitados acima nesta transação) sobrevive. A falha fica visível no log.
    from users.roles.promoter import service as promoter_iface

    try:
        with transaction.atomic():
            promoter_iface.maybe_auto_enroll_bolsista(lead.promoter)
    except Exception:
        logger.exception(
            "lead.bolsista_auto_enroll_failed", promoter=str(lead.promoter.external_id)
        )
    # G8/#5: esta indicação paga incrementa o paid_referrals do promotor; se ele é um student
    # bolsista que já completou docs, re-avalia a liberação da prova (senão fica preso). No-op senão.
    from users.roles.student import service as student_iface

    student_iface.reevaluate_exam_release(lead.promoter)
    return hub


def _notify_paid(lead: Lead, hub, checkout: Checkout | None = None) -> None:
    """Avisa lead + coordenador do hub + promotor (best-effort; cada canal isolado, §12).

    A notify do LEAD inclui o **comprovante** (`checkout.receipt_url`, que veio no webhook) — Victor.
    Migração 2026-07-02: usa `send_event` (Template no DB) — canais/is_tts/storytelling vêm do DB,
    `{nome}`/`{nome-completo}` resolvidos do profile. Trigger inativo → send_event devolve None (no-op).

    Issue #165 (2026-09-15): enriquecimento de contexto:
      - ALUNO recebe link direto para preenchimento de documentos.
      - COORDENADOR recebe dados do aluno (nome, telefone, polo) para acolhimento pedagógico.
      - PROMOTOR recebe progressão do bônus semanal (leads pagos / meta).
    """
    from notify.interface.events import send_event

    profile = profiles.get(lead.user)
    base = str(lead.external_id)

    def _safe(label, event, **kw):
        try:
            send_event(event, **kw)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"lead.notify_{label}_failed", external_id=base, error=str(exc)
            )

    # ── ALUNO: Parabéns + link de documentos ────────────────────────────────
    # Momento especial = parabéns por VOZ (sem URL na voz). O comprovante
    # vai numa mensagem SEPARADA de texto (URL não se lê em áudio).
    docs_link = config.enrollment_docs_url()
    _safe(
        "lead",
        "lead.paid",
        profile=profile,
        ctx={"docs_link": docs_link} if docs_link else None,
        idempotency_key=f"lead_paid_{base}",
    )
    receipt = checkout.receipt_url if checkout else None
    if receipt:
        _safe(
            "receipt",
            "lead.paid.receipt",
            profile=profile,
            ctx={"valor": f"R${checkout.amount}", "link": receipt},
            idempotency_key=f"lead_paid_receipt_{base}",
        )

    # ── COORDENADOR: dados do aluno para recepção pedagógica ─────────────────
    coord = hub.coordinator if hub else None
    if coord is not None:
        coord_profile = profiles.get(coord)
        lead_name = (profile.name if profile else None) or "Novo aluno"
        lead_phone = (profile.phone if profile else None) or "-"
        hub_name = getattr(hub, "brand", None) or "Polo"
        _safe(
            "coordinator",
            "lead.paid.coordinator",
            profile=coord_profile,
            ctx={
                "aluno_nome": lead_name,
                "aluno_telefone": lead_phone,
                "polo_nome": hub_name,
            },
            idempotency_key=f"lead_paid_coord_{base}",
        )

    # ── PROMOTOR: comissão + progressão do bônus semanal ─────────────────────
    # auto-matrícula de promotor: NÃO manda "seu indicado pagou / comissão" — o promotor é o próprio
    # aluno e não há comissão (Victor 2026-06-16).
    if not lead.self_study:
        promoter_profile = profiles.get(lead.promoter)
        # Calcula progressão semanal do bônus
        bonus_ctx = _weekly_bonus_context(lead.promoter)
        lead_name = (profile.name if profile else None) or "Um aluno"
        ctx = {"aluno_nome": lead_name, **bonus_ctx}
        _safe(
            "promoter",
            "lead.paid.promoter",
            profile=promoter_profile,
            ctx=ctx,
            idempotency_key=f"lead_paid_promoter_{base}",
        )


def _weekly_bonus_context(promoter_user) -> dict:
    """Calcula o contexto de bônus semanal para a notificação do promotor (Issue #165).

    Retorna dict com: comissao_direta, leads_semana, meta_bonus, falta_para_bonus.
    Best-effort — se falhar, retorna dict vazio (não trava a notify).
    """
    try:
        from finance import config as fin_config
        from finance.interface.commissions import week_window
        from finance.models import Commission

        week_start, week_end = week_window()
        leads_semana = Commission.objects.filter(
            payee=promoter_user,
            source_type=Commission.Source.LEAD,
            created_at__gte=week_start,
            created_at__lt=week_end,
        ).count()
        comissao_direta = fin_config.direct_amount()
        meta_bonus = fin_config.bonus_threshold()
        falta = max(0, meta_bonus - leads_semana)
        return {
            "comissao_direta": f"R${comissao_direta}",
            "leads_semana": str(leads_semana),
            "meta_bonus": str(meta_bonus),
            "falta_para_bonus": str(falta),
        }
    except Exception as exc:
        logger.warning("lead.bonus_context_failed", error=str(exc))
        return {}


def list_leads(*, hub=None, status=None, created_after=None, limit=None) -> list[Lead]:
    """Lista leads (mais novos primeiro), opcionalmente filtrados por HUB (do polo), status,
    data mínima (`created_after`) e `limit`.

    HUB = o polo do lead: o promotor pertence ao hub (`Promoter.hub`) OU a matrícula já está no hub
    (`Enrollment.hub`, pós-pagamento). Sem hub → todos (staff/tools). Coordenador passa o seu hub."""
    from django.db.models import Q

    qs = Lead.objects.select_related("user", "promoter", "checkout").order_by(
        "-created_at"
    )
    if status:
        qs = qs.filter(status=status)
    if created_after is not None:
        qs = qs.filter(created_at__gte=created_after)
    if hub is not None:
        qs = qs.filter(
            Q(promoter__promoter__hub=hub) | Q(user__enrollment__hub=hub)
        ).distinct()
    if limit is not None:
        qs = qs[:limit]
    return list(qs)


def lead_to_dict(lead: Lead, profile=None) -> dict:
    """Lead pra listagem do hub/staff: dados + LINK de pagamento + COMPROVANTE (Victor)."""
    c = getattr(lead, "checkout", None)
    p = profile if profile is not None else profiles.get(lead.user)
    return {
        "external_id": str(lead.external_id),
        "status": lead.status,
        "name": p.name if p else None,
        "phone": p.phone if p else None,
        "promoter_external_id": str(lead.promoter.external_id),
        "payment_link": checkout_links.short_url(c.short_token) if c else None,
        "receipt_url": c.receipt_url if c else None,
        "created_at": lead.created_at.isoformat(),
    }


def get_by_external_id(external_id: str) -> Lead | None:
    """Busca um lead específico por external_id."""
    return (
        Lead.objects.select_related("user", "promoter", "checkout", "attribution")
        .filter(external_id=external_id)
        .first()
    )


def get_lead_for_hub(*, external_id: str, hub) -> Lead | None:
    """Um lead específico, SÓ se pertence ao polo — a MESMA régua da listagem (`list_leads`):
    hub do promotor que captou OU hub da matrícula pós-pagamento. None = não existe / não é do
    polo (a borda devolve 404 sem vazar existência pra outro coordenador — plan/14)."""
    from django.db.models import Q

    return (
        Lead.objects.filter(external_id=external_id)
        .filter(Q(promoter__promoter__hub=hub) | Q(user__enrollment__hub=hub))
        .select_related("user", "promoter", "checkout")
        .distinct()
        .first()
    )


def mark_refunded(*, provider: str, provider_payment_id: str) -> bool:
    """Processa o estorno/cancelamento de um pagamento de lead.
    
    1. Localiza o Checkout pelo provider e provider_payment_id.
    2. Atualiza lead e checkout para status cancelado / estornado.
    3. Cancela a Commission associada (se ainda PENDING).
    """
    checkout = (
        Checkout.objects.select_related("lead", "lead__user", "lead__promoter")
        .filter(provider=provider, provider_payment_id=provider_payment_id)
        .first()
    )
    if checkout is None:
        return False

    lead = checkout.lead
    with transaction.atomic():
        checkout.is_paid = False
        checkout.save(update_fields=["is_paid", "updated_at"])
        lead.status = Lead.Status.FAILED
        lead.failed_reason = "payment_refunded"
        lead.save(update_fields=["status", "failed_reason", "updated_at"])

        from finance.models import Commission

        Commission.objects.filter(
            source_type=Commission.Source.LEAD,
            source_external_id=lead.external_id,
            status=Commission.Status.PENDING,
        ).update(status=Commission.Status.CANCELLED)

    logger.info("lead.refunded", external_id=str(lead.external_id), provider=provider)
    return True

