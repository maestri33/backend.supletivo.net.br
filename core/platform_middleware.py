from django.conf import settings


class PlatformVersionMiddleware:
    """Adiciona discretamente o header HTTP X-Platform-Version em todas as respostas da API."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-Platform-Version"] = getattr(
            settings, "APP_VERSION", "0.0.0-sandbox.20"
        )
        return response
