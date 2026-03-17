"""
Set up the database with test orgs, partners, and certificates for load testing.

Usage:
    python manage.py migrate
    python manage.py setup_loadtest
    python manage.py runserver 0.0.0.0:8000
"""
import os

from django.core.management.base import BaseCommand

from pyas2.models import Organization, Partner, PrivateKey, PublicCertificate
from pyas2.tests import TEST_DIR


class Command(BaseCommand):
    help = "Set up test data for AS2 load testing"

    def handle(self, *args, **options):
        # Load certificates
        with open(os.path.join(TEST_DIR, "server_private.pem"), "rb") as fp:
            server_key_data = fp.read()
        with open(os.path.join(TEST_DIR, "server_public.pem"), "rb") as fp:
            server_crt_data = fp.read()
        with open(os.path.join(TEST_DIR, "client_private.pem"), "rb") as fp:
            client_key_data = fp.read()
        with open(os.path.join(TEST_DIR, "client_public.pem"), "rb") as fp:
            client_crt_data = fp.read()

        server_key, _ = PrivateKey.objects.update_or_create(
            name="server_key",
            defaults=dict(key=server_key_data, key_pass="test"),
        )
        server_crt, _ = PublicCertificate.objects.update_or_create(
            name="server_crt",
            defaults=dict(certificate=server_crt_data),
        )
        client_key, _ = PrivateKey.objects.update_or_create(
            name="client_key",
            defaults=dict(key=client_key_data, key_pass="test"),
        )
        client_crt, _ = PublicCertificate.objects.update_or_create(
            name="client_crt",
            defaults=dict(certificate=client_crt_data),
        )

        # Server org (receives messages)
        Organization.objects.update_or_create(
            as2_name="as2server",
            defaults=dict(
                name="AS2 Server",
                encryption_key=server_key,
                signature_key=server_key,
            ),
        )

        # Client org (sends messages)
        Organization.objects.update_or_create(
            as2_name="as2client",
            defaults=dict(
                name="AS2 Client",
                encryption_key=client_key,
                signature_key=client_key,
            ),
        )

        # Partner representing the client (for receiving messages from client)
        Partner.objects.update_or_create(
            as2_name="as2client",
            defaults=dict(
                name="AS2 Client",
                target_url="http://localhost:8000/pyas2/as2receive",
                signature="sha256",
                signature_cert=client_crt,
                encryption="tripledes_192_cbc",
                encryption_cert=client_crt,
                mdn=True,
                mdn_mode="SYNC",
                mdn_sign="sha256",
            ),
        )

        # Partner representing the server (for sending messages to server)
        Partner.objects.update_or_create(
            as2_name="as2server",
            defaults=dict(
                name="AS2 Server",
                target_url="http://localhost:8000/pyas2/as2receive",
                signature="sha256",
                signature_cert=server_crt,
                encryption="tripledes_192_cbc",
                encryption_cert=server_crt,
                mdn=True,
                mdn_mode="SYNC",
                mdn_sign="sha256",
            ),
        )

        self.stdout.write(self.style.SUCCESS(
            "Load test data created:\n"
            "  - Organization: as2server (receives)\n"
            "  - Organization: as2client (sends)\n"
            "  - Partner: as2client (signature + encryption)\n"
            "  - Partner: as2server (signature + encryption)\n"
            "\nReady for load testing. Start the server with:\n"
            "  python manage.py runserver 0.0.0.0:8000\n"
        ))