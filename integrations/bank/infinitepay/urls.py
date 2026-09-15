from django.urls import path

from . import views

app_name = "infinitepay"

# Só o webhook PÚBLICO chamado de fora pela infinitepay.prod (sem auth; trava = order_nsu opaco +
# payment_check). O status/checkout (consumidos in-process pelo lead) eram DMZ — FECHADOS (Victor
# 2026-06-16): saúde da integração agora vive no grupo Ninja `staff`.
urlpatterns = [
    path("webhook/", views.webhook, name="webhook"),
]
