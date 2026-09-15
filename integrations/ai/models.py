"""Models do app integrations.ai — auditoria/custo de cada chamada de IA (pedido do Victor, Portão 1 Q3).

Design NOVO (o micro `ai` legado não tinha tabelas — só um schema vazio). É **telemetria interna**:
não tem borda de API, então **não tem `external_id`** (CONVENTION §4: external_id só na borda). Uma
linha por chamada, gravada pela interface (service.py).

`cost` fica **null** por enquanto: DeepSeek cobra por token e o preço é dinheiro real — não invento
(CONVENTION §8). Quando o Victor passar a tabela de preços + moeda, o cálculo entra aqui.
"""

from django.db import models


class AiCall(models.Model):
    """Registro de uma chamada a um provedor de IA: o quê, quem chamou, tokens, custo, latência.

    `provider` é campo LIVRE (não choices): os providers vêm do `.env` (deepseek, dashscope, groq,
    openai, openrouter, nvidia, …) e somar um novo é só config — o banco não precisa saber a lista.
    Uma chamada com fallback gera VÁRIAS linhas: a(s) tentativa(s) que falhou (status=error) + a que
    deu certo (status=success).
    """

    class Operation(models.TextChoices):
        JSON = "json", "json"
        SUMMARIZE = "summarize", "summarize"
        GRADE = "grade", "grade"
        VISION = "vision", "vision"
        OCR = "ocr", "ocr"
        STT = "stt", "stt"

    class Status(models.TextChoices):
        SUCCESS = "success", "success"
        ERROR = "error", "error"

    provider = models.CharField(max_length=20, db_index=True)
    operation = models.CharField(max_length=20, choices=Operation.choices)
    model = models.CharField(max_length=60)
    # Quem chamou (nome do app/feature consumidor, ex.: "training"). O chamador informa.
    caller = models.CharField(max_length=60, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices)

    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    cache_hit_tokens = models.IntegerField(default=0)
    cache_miss_tokens = models.IntegerField(default=0)
    # Custo monetário da chamada. Null até a tabela de preços ser definida (CONVENTION §8 — não invento $$).
    cost = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    latency_ms = models.IntegerField()

    finish_reason = models.CharField(max_length=40, null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["created_at"])]

    def __str__(self):
        return f"{self.provider}:{self.operation} {self.status} ({self.caller})"
