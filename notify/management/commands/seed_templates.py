"""Comando para popular e atualizar o catálogo de templates de notificação do backend."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from notify.models import Template, Trigger
from notify.seed import io as seed_io


class Command(BaseCommand):
    help = "Popula/atualiza templates de notificação a partir de notify/seed/templates.md"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Sobrescreve alterações feitas em banco com o conteúdo do seed.",
        )
        parser.add_argument(
            "--path",
            type=str,
            default="",
            help="Caminho alternativo para o templates.md",
        )

    def handle(self, *args, **options):
        force = options["force"]
        raw_path = options["path"]
        if raw_path:
            file_path = Path(raw_path)
        else:
            file_path = Path(__file__).resolve().parents[2] / "seed" / "templates.md"

        if not file_path.exists():
            self.stderr.write(self.style.ERROR(f"Arquivo de seed não encontrado: {file_path}"))
            return

        text = file_path.read_text(encoding="utf-8")
        specs = seed_io.parse(text)
        created_count = 0
        updated_count = 0
        skipped_count = 0

        with transaction.atomic():
            for spec in specs:
                tpl, created = Template.objects.get_or_create(
                    event=spec.event,
                    defaults={
                        "title": spec.title,
                        "subject": spec.subject,
                        "body_md": spec.body_md,
                        "is_tts": spec.is_tts if hasattr(spec, "is_tts") else False,
                        "channels": spec.channels,
                        "media_url": spec.media_url,
                        "media_type": spec.media_type,
                        "mail_template": spec.mail_template,
                    },
                )
                if created:
                    created_count += 1
                elif force:
                    tpl.title = spec.title
                    tpl.subject = spec.subject
                    tpl.body_md = spec.body_md
                    tpl.is_tts = spec.is_tts if hasattr(spec, "is_tts") else False
                    tpl.channels = spec.channels
                    tpl.media_url = spec.media_url
                    tpl.media_type = spec.media_type
                    tpl.mail_template = spec.mail_template
                    tpl.save()
                    updated_count += 1
                else:
                    skipped_count += 1

                tr, _ = Trigger.objects.get_or_create(
                    template=tpl,
                    defaults={
                        "fires_on": spec.fires_on or "",
                        "source": spec.source,
                        "delay_minutes": spec.delay_minutes,
                        "active": spec.active,
                    },
                )
                if force and not created:
                    tr.fires_on = spec.fires_on or ""
                    tr.source = spec.source
                    tr.delay_minutes = spec.delay_minutes
                    tr.active = spec.active
                    tr.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Templates de Notificação: {created_count} criados, {updated_count} atualizados, {skipped_count} ignorados."
            )
        )
