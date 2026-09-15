"""Testes para utilitários de requisição HTTP e extração de IP real."""

from django.test import RequestFactory

from core.request import get_client_ip


def test_get_client_ip_prioritizes_cf_connecting_ip():
    factory = RequestFactory()
    request = factory.get("/", HTTP_CF_CONNECTING_IP="203.0.113.195", HTTP_X_FORWARDED_FOR="10.1.30.10, 192.168.1.1", REMOTE_ADDR="10.1.30.101")
    assert get_client_ip(request) == "203.0.113.195"


def test_get_client_ip_fallback_to_x_forwarded_for():
    factory = RequestFactory()
    request = factory.get("/", HTTP_X_FORWARDED_FOR="198.51.100.42, 10.1.30.10", REMOTE_ADDR="10.1.30.101")
    assert get_client_ip(request) == "198.51.100.42"


def test_get_client_ip_fallback_to_remote_addr():
    factory = RequestFactory()
    request = factory.get("/", REMOTE_ADDR="192.0.2.1")
    assert get_client_ip(request) == "192.0.2.1"


def test_get_client_ip_default():
    factory = RequestFactory()
    request = factory.get("/")
    request.META["REMOTE_ADDR"] = ""
    assert get_client_ip(request) == "127.0.0.1"
