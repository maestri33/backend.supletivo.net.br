from types import SimpleNamespace
from unittest.mock import Mock

from users.roles.enrollment import service, rg_decision


def test_selfie_rejection_supplies_template_app_link(monkeypatch):
    from notify.interface import events

    send = Mock()
    monkeypatch.setattr(events, "send_event", send)
    monkeypatch.setattr(rg_decision.profiles, "get", lambda user: None)
    monkeypatch.setattr(rg_decision, "_resume_link", lambda: "https://app.supletivo.net.br/student/enrollment/selfie")
    rg_decision._notify_resolution(SimpleNamespace(user=object()), "enrollment.selfie_rejected")
    ctx = send.call_args.kwargs["ctx"]
    assert ctx["link_app"] == "https://app.supletivo.net.br/student/enrollment/selfie"
    assert ctx["link"] == ctx["link_app"]
