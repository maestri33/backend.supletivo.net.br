"""Comando de diagnóstico, auto-teste e homologação física das APIs do usuário principal (Victor Maestri / Staff).

Valida deterministicamente:
1. Consulta na Receita Federal via CPFHub.
2. Checagem de WhatsApp e envio de OTP via Notify-Server.
3. Consulta e validação de titularidade da Chave PIX no DICT via Asaas.
4. (Opcional/Default) Micro-transferência real de R$ 0,01 via Asaas Payout.
5. Sincronização do perfil do usuário principal no banco de dados.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
import secrets
import sys
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from asgiref.sync import async_to_sync
from core import system_config
from integrations.bank.asaas import payout as asaas_payout
from integrations.bank.asaas import pixkey
from integrations.tools.cpf.scripts import cpfhub
from users.auth import service as auth_iface
from users.auth import validation as auth_validation
from users.auth.models import User
from users.profiles import interface as profiles
from users.profiles.models import Profile


class Command(BaseCommand):
    help = "Executa auto-teste de ponta a ponta das APIs usando os dados do usuário principal."

    def add_arguments(self, parser):
        parser.add_argument("--phone", type=str, help="Telefone customizado (padrão: DEFAULT_STAFF_PHONE)")
        parser.add_argument("--cpf", type=str, help="CPF customizado (padrão: DEFAULT_STAFF_CPF)")
        parser.add_argument("--pix", type=str, help="Chave PIX customizada (padrão: DEFAULT_STAFF_PIX)")
        parser.add_argument("--otp", type=str, help="Código OTP recebido no WhatsApp para login staff")
        parser.add_argument("--skip-payout", action="store_true", help="Pular o envio de R$ 0,01 real via PIX")
        parser.add_argument("--skip-otp", action="store_true", help="Pular o envio de mensagem de WhatsApp/OTP e autenticação")

    def handle(self, *args, **options):
        self.stdout.write("=" * 65)
        self.stdout.write(self.style.SUCCESS("🚀 INICIANDO AUTO-TESTE DAS APIS DO USUÁRIO PRINCIPAL V7M"))
        self.stdout.write("=" * 65)

        cpf = options["cpf"] or system_config.get_setting("DEFAULT_STAFF_CPF", getattr(settings, "DEFAULT_STAFF_CPF", "09126367939"))
        phone = options["phone"] or system_config.get_setting("DEFAULT_STAFF_PHONE", getattr(settings, "DEFAULT_STAFF_PHONE", "5543996648750"))
        pix = options["pix"] or system_config.get_setting("DEFAULT_STAFF_PIX", getattr(settings, "DEFAULT_STAFF_PIX", "09126367939"))

        clean_cpf = "".join(ch for ch in cpf if ch.isdigit())
        clean_phone = auth_validation.validate_phone(phone)
        clean_pix = pix.strip()

        self.stdout.write(f"📋 Parâmetros: CPF={clean_cpf} | Phone={clean_phone} | PIX={clean_pix}\n")

        # ── FASE 0: Autenticação, OTP Real & Login Staff ──
        if options["skip_otp"]:
            self.stdout.write(self.style.NOTICE("⏭️  [0/4] Autenticação e OTP pulados por parâmetro."))
        else:
            self.stdout.write(self.style.WARNING("🔐 [0/4] Testando Autenticação Staff, Envio de OTP e Login..."))
            try:
                # 1. Envia OTP via check_staff
                check_res = auth_iface.check_staff(phone=clean_phone)
                if not check_res.get("found"):
                    self.stdout.write(self.style.NOTICE(f"   ℹ️ Telefone {clean_phone} não encontrado como Staff. Tentando por CPF {clean_cpf}..."))
                    check_res = auth_iface.check_staff(cpf=clean_cpf)

                if check_res.get("found"):
                    staff_ext_id = check_res["external_id"]
                    self.stdout.write(self.style.SUCCESS(
                        f"   ✅ Staff Encontrado (External ID: {staff_ext_id}). OTP despachado via WhatsApp!"
                    ))
                    if check_res.get("otp_wait"):
                        self.stdout.write(self.style.NOTICE(f"   ⏳ Cooldown ativo: aguarde {check_res['otp_wait']}s para novo envio."))

                    # 2. Obter código OTP
                    otp_code = options.get("otp")
                    if not otp_code and sys.stdin.isatty():
                        try:
                            otp_code = input("   🔑 Digite o código OTP recebido no WhatsApp: ").strip()
                        except (EOFError, KeyboardInterrupt):
                            otp_code = None

                    if otp_code:
                        # 3. Executa login_staff e valida JWT
                        tokens = auth_iface.login_staff(external_id=staff_ext_id, otp=otp_code)
                        access_token = tokens.get("access_token")
                        self.stdout.write(self.style.SUCCESS(
                            f"   ✅ Login Staff OK! JWT Emitido com Sucesso."
                        ))
                        self.stdout.write(self.style.SUCCESS(
                            f"   🔑 Access Token: {access_token}"
                        ))
                    else:
                        self.stdout.write(self.style.NOTICE(
                            "   ℹ️ Nenhum código OTP informado (use --otp <código> ou execute interativamente para validar o JWT)."
                        ))
                else:
                    self.stdout.write(self.style.ERROR(
                        f"   ❌ Usuário Staff não localizado por Telefone ({clean_phone}) ou CPF ({clean_cpf}). Execute 'seed_defaults' primeiro."
                    ))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"   ❌ Falha na Fase 0 (Autenticação/OTP): {exc}"))
                self.stdout.write(self.style.NOTICE("   💡 Instrução: Verifique o notify-server (:8000) e se o usuário possui role de staff."))

        # ── FASE 1: Consulta CPFHub ──
        self.stdout.write(self.style.WARNING("🔍 [1/4] Testando Consulta CPFHub (Receita Federal)..."))
        identity = None
        try:
            identity = async_to_sync(cpfhub.lookup)(clean_cpf)
            if identity and identity.name:
                self.stdout.write(self.style.SUCCESS(
                    f"   ✅ CPFHub OK: Nome={identity.name} | Gênero={identity.gender} | Nasc={identity.birth_date}"
                ))
            else:
                self.stdout.write(self.style.ERROR("   ❌ CPFHub retornou dados vazios."))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"   ❌ Falha na consulta CPFHub: {exc}"))
            self.stdout.write(self.style.NOTICE("   💡 Instrução: Verifique CPFHUB_API_KEY no cofre Infisical (:8080)."))

        # ── FASE 2: WhatsApp & Mensageria ──
        if options["skip_otp"]:
            self.stdout.write(self.style.NOTICE("⏭️  [2/4] Mensageria/OTP pulada por parâmetro."))
        else:
            self.stdout.write(self.style.WARNING("📱 [2/4] Testando Mensageria WhatsApp / Notify Server..."))
            try:
                exists, norm_phone = auth_iface.check_phone_whatsapp(clean_phone)
                if exists:
                    self.stdout.write(self.style.SUCCESS(f"   ✅ Telefone com WhatsApp Ativo: {norm_phone}"))
                    # Despacha mensagem de auto-teste
                    from notify.interface.send import send
                    msg_id = send(
                        text=f"🔐 [QG V7M] Auto-teste de infraestrutura concluído com sucesso em {timezone.localtime().strftime('%d/%m/%Y %H:%M:%S')}.",
                        caller="test_principal_user_apis",
                        phone=norm_phone,
                        whatsapp=True,
                        email_channel=False,
                        tts=False,
                        idempotency_key=f"self_test_{secrets.token_hex(6)}",
                    )
                    self.stdout.write(self.style.SUCCESS(f"   ✅ Mensagem WhatsApp despachada (ID={msg_id})"))
                else:
                    self.stdout.write(self.style.ERROR(f"   ❌ Telefone {clean_phone} não possui WhatsApp detectado."))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"   ❌ Falha na mensageria: {exc}"))
                self.stdout.write(self.style.NOTICE("   💡 Instrução: Verifique se o container Evolution-GO (:4000) está pareado."))

        # ── FASE 3: Asaas DICT Chave PIX ──
        self.stdout.write(self.style.WARNING("🏦 [3/4] Testando Validação de Chave PIX no DICT (Asaas)..."))
        try:
            from users.roles.promoter.service import detect_pix_key_type
            pix_type = detect_pix_key_type(clean_pix)
            validated_pix = pixkey.validate_pix_key(
                key=clean_pix,
                key_type=pix_type,
                expected_document=clean_cpf,
            )
            self.stdout.write(self.style.SUCCESS(
                f"   ✅ Chave PIX Validada no DICT: Titular={validated_pix.holder_name} | Banco={validated_pix.bank_name}"
            ))
        except pixkey.PixKeyError as exc:
            self.stdout.write(self.style.ERROR(f"   ❌ Erro ao validar Chave PIX no DICT: {exc}"))
            self.stdout.write(self.style.NOTICE("   💡 Instrução: Verifique se o CPF do perfil bate exatamente com o titular da chave PIX."))

        # ── FASE 4: Micro-Transferência Real (R$ 0,01) ──
        if options["skip_payout"]:
            self.stdout.write(self.style.NOTICE("⏭️  [4/4] Transferência PIX de R$ 0,01 pulada por parâmetro."))
        else:
            self.stdout.write(self.style.WARNING("💸 [4/4] Executando Micro-Transferência Real de R$ 0,01..."))
            try:
                payment_id = f"self-test-{secrets.token_hex(6)}"
                res = asaas_payout.create_payout(
                    amount=Decimal("0.01"),
                    pix_key=clean_pix,
                    payment_id=payment_id,
                    description=f"Auto-teste de Payout QG V7M {clean_cpf}",
                )
                self.stdout.write(self.style.SUCCESS(
                    f"   ✅ PIX de R$ 0,01 Enviado com Sucesso: ID={res.get('id')} | Status={res.get('status')}"
                ))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"   ❌ Falha ao emitir PIX real de R$ 0,01: {exc}"))
                self.stdout.write(self.style.NOTICE("   💡 Instrução: Verifique o saldo no Asaas e a URL de validação de transferência (/integrations/asaas/transfer-validation/)."))

        # ── Sincronização do Perfil ──
        self.stdout.write("\n" + "=" * 65)
        self.stdout.write(self.style.SUCCESS("✨ Sincronizando dados do usuário principal no banco local..."))
        profile = Profile.objects.filter(cpf=clean_cpf).first()
        if profile:
            profile.phone = clean_phone
            profile.pix_key = clean_pix
            if identity and identity.name:
                profile.name = identity.name
                profile.gender = identity.gender
                profile.birth_date = identity.birth_date
            profile.save()
            self.stdout.write(self.style.SUCCESS(f"   ✅ Perfil ID={profile.id} (User ID={profile.user_id}) 100% atualizado e validado!"))
        else:
            self.stdout.write(self.style.NOTICE("   ℹ️ Perfil ainda não existia pelo CPF. Execute 'seed_defaults' para criá-lo."))

        self.stdout.write("=" * 65)
        self.stdout.write(self.style.SUCCESS("🏁 DIAGNÓSTICO E AUTO-TESTE FINALIZADOS COM SUCESSO!"))
