from django.urls import path

from . import views

app_name = "asaas"

# Só os endpoints PÚBLICOS chamados de fora pela asaas.prod. O onboarding/health (status/setup) e
# charge/payout (consumidos in-process pelo lead/finance) eram DMZ sem-auth — FECHADOS (Victor
# 2026-06-16): saúde/ações da integração agora vivem no grupo Ninja `staff` (require_superuser).
urlpatterns = [
    # auth = header asaas-access-token (== ASAAS_WEBHOOK_SECRET)
    path("webhook/", views.webhook, name="webhook"),
    path("transfer-validation/", views.transfer_validation, name="transfer-validation"),
    # echo do ping de verificação da URL (auth = nonce single-use)
    path("url-verify/<str:nonce>/", views.url_verify_echo, name="url-verify"),
]
