from django import forms
from django.contrib.auth.forms import AuthenticationForm


class AdminAuthenticationForm(AuthenticationForm):
    """Form de login do Admin customizado.

    O `AuthenticationForm` padrão do Django ajusta `username.widget.attrs['maxlength']`
    no `__init__` com base no `max_length` do modelo. Como `external_id` é `UUIDField` (sem `max_length`),
    o Django define um fallback de 32 caracteres. Forçamos para 64 para aceitar o UUID de 36 caracteres.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs["maxlength"] = 64
        self.fields["username"].widget.attrs["autofocus"] = True
        self.fields["username"].label = "External ID (UUID)"
