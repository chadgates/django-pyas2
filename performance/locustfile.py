"""
Locust load test for django-pyas2 AS2 receive endpoint.

Pre-builds AS2 messages at startup using test certificates, then sends them
as HTTP POSTs to the /pyas2/as2receive/ endpoint.

Supports configurable payload sizes via PAYLOAD_SIZE env var (default: 500KB).

Usage:
    1. Start the Django server (ASGI):
       USE_POSTGRES=True uvicorn example.asgi:application --host 0.0.0.0 --port 8000

    2. Run locust (headless):
       locust -f locustfile.py --host http://localhost:8000 \
              --users 10 --spawn-rate 10 --run-time 30s --headless

    3. Or with web UI:
       locust -f locustfile.py --host http://localhost:8000
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example.settings")

import django
django.setup()

from locust import HttpUser, task, events
from uuid import uuid4

from pyas2lib import Message as As2Message
from pyas2lib import Organization as As2Organization
from pyas2lib import Partner as As2Partner

from pyas2.tests import TEST_DIR

# ── Configuration ────────────────────────────────────────────────────────────────

PAYLOAD_SIZE_KB = int(os.environ.get("PAYLOAD_SIZE_KB", "500"))

# ── Load certs and build payload ─────────────────────────────────────────────────

def _load_cert(filename):
    with open(os.path.join(TEST_DIR, filename), "rb") as f:
        return f.read()

_server_pub = _load_cert("server_public.pem")
_client_priv = _load_cert("client_private.pem")
_client_pub = _load_cert("client_public.pem")

# Build a realistic EDI payload of the target size
_edi_header = (
    b"UNB+UNOA:2+SENDER:14+RECEIVER:14+140407:0910+%b++++1+EANCOM'\n"
    b"UNH+1+ORDERS:D:96A:UN:EAN008'\n"
    b"BGM+220+LOADTEST+9'\n"
)
_edi_line = b"LIN+%d++9783898307529:EN'\nQTY+21:5'\nPRI+AAA:27.50'\n"
_edi_footer = b"UNS+S'\nCNT+2:1'\nUNT+26+1'\nUNZ+1+5'\n"

def _build_payload(target_kb):
    """Build an EDI payload of approximately target_kb kilobytes."""
    parts = [_edi_header]
    line_num = 1
    while len(b"".join(parts)) < target_kb * 1024:
        parts.append(_edi_line.replace(b"%d", str(line_num).encode()))
        line_num += 1
    parts.append(_edi_footer)
    payload = b"".join(parts)
    return payload

_payload = _build_payload(PAYLOAD_SIZE_KB)
print(f"[locust] Payload size: {len(_payload) / 1024:.1f} KB")


def _build_as2_message(encrypt, sign, payload):
    """Build a complete AS2 message ready to POST."""
    org_params = {"as2_name": "as2client"}
    partner_params = {
        "as2_name": "as2server",
        "mdn_mode": "SYNC",
        "mdn_digest_alg": "sha256" if sign else None,
    }
    if sign:
        org_params["sign_key"] = _client_priv
        org_params["sign_key_pass"] = "test"
        partner_params["verify_cert"] = _client_pub
    if encrypt:
        partner_params["encrypt_cert"] = _server_pub
        partner_params["enc_alg"] = "tripledes_192_cbc"

    sender = As2Organization(**org_params)
    receiver = As2Partner(**partner_params)
    as2msg = As2Message(sender=sender, receiver=receiver)
    as2msg.build(
        payload,
        filename="loadtest.edi",
        subject="EDI Message",
        content_type="application/edi-consent",
        disposition_notification_to="no-reply@pyas2.com",
    )
    return as2msg


# ── Pre-build scenarios ──────────────────────────────────────────────────────────

_scenarios = {}

def _prebuild():
    configs = [
        ("plain",            False, False),
        ("signed",           False, True),
        ("encrypted",        True,  False),
        ("encrypted_signed", True,  True),
    ]
    for name, enc, sgn in configs:
        msg = _build_as2_message(enc, sgn, _payload)
        _scenarios[name] = {
            "headers": dict(msg.headers),
            "content": msg.content,
        }
        size_kb = len(msg.content) / 1024
        print(f"[locust] Pre-built '{name}': {size_kb:.1f} KB on the wire")

_prebuild()


def _post_kwargs(scenario_name):
    """Build kwargs for locust client.post()."""
    sc = _scenarios[scenario_name]
    headers = dict(sc["headers"])
    headers["message-id"] = f"<{uuid4()}@locust>"
    return {"data": sc["content"], "headers": headers}


# ── Locust User classes ──────────────────────────────────────────────────────────

class AS2PlainUser(HttpUser):
    """Unencrypted, unsigned."""
    weight = 1

    @task
    def send(self):
        self.client.post("/pyas2/as2receive/", **_post_kwargs("plain"))


class AS2SignedUser(HttpUser):
    """Signed only."""
    weight = 2

    @task
    def send(self):
        self.client.post("/pyas2/as2receive/", **_post_kwargs("signed"))


class AS2EncryptedUser(HttpUser):
    """Encrypted only."""
    weight = 2

    @task
    def send(self):
        self.client.post("/pyas2/as2receive/", **_post_kwargs("encrypted"))


class AS2EncryptedSignedUser(HttpUser):
    """Encrypted + signed (most realistic production scenario)."""
    weight = 5

    @task
    def send(self):
        self.client.post("/pyas2/as2receive/", **_post_kwargs("encrypted_signed"))