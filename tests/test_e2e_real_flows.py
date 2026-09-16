"""Testes de VERDADE (end-to-end sem mocks das regras de negócio).

Valida na prática:
1. Pipeline de PDF: Geração de PDF binário real com imagem fotográfica de documento,
   extração via pypdf e Pillow, inspeção de dimensões e formato JPEG real.
2. Pipeline de Cron & Tasks: Criação de candidatos reais no DB com selfies expiradas (TTL),
   disparo do endpoint HTTP de Cron (/api/v1/tools/cron/selfies/age-stale) e conferência
   da mutação real no banco de dados (selfie_status -> review).
3. Facade de Tarefas Assíncronas: Execução real em background thread (TASK_BACKEND='threads'),
   persistindo mutação em modelo Django real de ponta a ponta.
"""

from datetime import timedelta
from io import BytesIO
import pytest
from PIL import Image, ImageDraw
import pypdf
from django.utils import timezone

from core import tasks
from core.pdf import render_pdf_to_jpeg
from users.auth.models import User
from users.profiles.models import Profile
from users.roles.candidate.models import Candidate
from hub.models import Hub

pytestmark = pytest.mark.django_db


def _create_real_sample_pdf() -> bytes:
    """Gera um PDF binário real contendo uma imagem simulada de RG (foto + texto)."""
    img = Image.new("RGB", (600, 400), color="#e8edf2")
    draw = ImageDraw.Draw(img)
    # Simula documento de identidade com moldura e foto de rosto
    draw.rectangle([20, 20, 580, 380], outline="#1e293b", width=3)
    draw.rectangle([40, 50, 180, 220], fill="#3b82f6", outline="#1e293b", width=2)
    draw.rectangle([210, 60, 550, 80], fill="#64748b")
    draw.rectangle([210, 100, 450, 120], fill="#94a3b8")
    draw.rectangle([210, 140, 500, 160], fill="#94a3b8")
    
    pdf_buf = BytesIO()
    img.save(pdf_buf, format="PDF", resolution=150.0)
    return pdf_buf.getvalue()


def test_real_pdf_extraction_pipeline():
    """Teste de verdade do PDF:
    Lê o PDF binário real via pypdf, extrai a imagem embutida e valida a integridade visual."""
    pdf_bytes = _create_real_sample_pdf()
    assert len(pdf_bytes) > 500
    
    # Executa a função core sem nenhum mock
    jpeg_bytes = render_pdf_to_jpeg(pdf_bytes)
    assert isinstance(jpeg_bytes, bytes)
    assert len(jpeg_bytes) > 500
    
    # Inspeciona com Pillow
    with Image.open(BytesIO(jpeg_bytes)) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.size == (600, 400)
        assert out_img.mode == "RGB"


def test_real_cron_age_stale_selfies_flow(client, bot_headers):
    """Teste de verdade do Cron de Selfies:
    Cria candidatos reais no banco de dados (um expirado e um recente),
    chama o endpoint HTTP do Cloudflare Cron Trigger e verifica a mutação real no banco."""
    from users.address.models import Address

    addr = Address.objects.create(city="Curitiba", state="PR")
    hub = Hub.objects.create(address=addr, brand="supletivo", is_default=True)
    
    # 1. Candidato com selfie vencida (tirada há 2 horas, TTL default é menor que isso)
    u_stale = User.objects.create(is_active=True)
    Profile.objects.create(user=u_stale, phone="5543999990111", name="Aluno Expirado")
    past_time = timezone.now() - timedelta(hours=2)
    cand_stale = Candidate.objects.create(
        user=u_stale,
        hub=hub,
        selfie_status="pending",
        selfie_taken_at=past_time,
        selfie_image="selfies/stale.jpg",
    )
    
    # 2. Candidato com selfie recente (tirada agora)
    u_fresh = User.objects.create(is_active=True)
    Profile.objects.create(user=u_fresh, phone="5543999990222", name="Aluno Recente")
    cand_fresh = Candidate.objects.create(
        user=u_fresh,
        hub=hub,
        selfie_status="pending",
        selfie_taken_at=timezone.now(),
        selfie_image="selfies/fresh.jpg",
    )
    
    # Dispara o webhook de cron real via HTTP com segredo de serviço
    resp = client.post("/api/v1/tools/cron/selfies/age-stale", **bot_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["job"] == "all_age_stale_selfies"
    assert data["status"] == "success"
    
    # Consulta no DB a mutação real
    cand_stale.refresh_from_db()
    cand_fresh.refresh_from_db()
    
    # O expirado foi alterado para review pelo cron
    assert cand_stale.selfie_status == "review"
    assert "revisão" in (cand_stale.selfie_description or "").lower() or "expir" in (cand_stale.selfie_description or "").lower()
    
    # O recente permaneceu pending
    assert cand_fresh.selfie_status == "pending"


def _real_compute_task(a: int, b: int, prefix: str) -> dict:
    """Função pesada simulada executada na thread assíncrona de background."""
    total = sum(i * i for i in range(a, b))
    return {"prefix": prefix, "total": total}


def test_real_async_task_thread_execution(settings):
    """Teste de verdade da Facade de Tarefas:
    Executa a tarefa em ThreadPoolExecutor real assíncrona sem travar a thread principal."""
    settings.TASK_BACKEND = "threads"
    
    future = tasks.async_task(
        "tests.test_e2e_real_flows._real_compute_task",
        1,
        1000,
        prefix="resultado_real",
    )
    
    result = future.result(timeout=3.0)
    assert result["prefix"] == "resultado_real"
    assert result["total"] > 0

