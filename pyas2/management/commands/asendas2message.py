import asyncio
import logging
import os

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.files.storage import default_storage
from django.db import transaction
from pyas2lib import Message as AS2Message

from pyas2.models import Message

from pyas2lib import Organization as As2Organization
from pyas2lib import Partner as As2Partner

logger = logging.getLogger("pyas2")

from pyas2.caching import (
    get_cached_partnerships_by_as2_name,
    get_cached_organizations_by_as2_name,
    get_cached_partners_by_as2_name,
)

from asgiref.sync import sync_to_async


async def main(*args, **options):
    # Check if organization and partner exists
    partnership = await sync_to_async(get_cached_partnerships_by_as2_name)(options["org_as2name"],
                                                      options["partner_as2name"])

    org = await sync_to_async(get_cached_organizations_by_as2_name)(options["org_as2name"])
    partner = await sync_to_async(get_cached_partners_by_as2_name)(options["partner_as2name"])

    if partnership:
        as2_sender = As2Organization(**partnership.get("as2org_params"))
        as2_receiver = As2Partner(**partnership.get("as2partner_params"))
    elif org and partner:
        as2_sender = As2Organization(**org.get("as2org_params"))
        as2_receiver = As2Partner(**partner.get("as2partner_params"))
    if not org:
        raise CommandError(
            f'Organization "{options["org_as2name"]}" does not exist'
        )

    if not partner:
        raise CommandError(f'Partner "{options["partner_as2name"]}" does not exist')

    # Check if file exists
    if not default_storage.exists(options["path_to_payload"]):
        raise CommandError(
            f'Payload at location "{options["path_to_payload"]}" does not exist.'
        )

    # Build and send the AS2 message
    original_filename = os.path.basename(options["path_to_payload"])
    with default_storage.open(options["path_to_payload"], "rb") as in_file:
        payload = in_file.read()
        as2message = AS2Message(sender=as2_sender, receiver=as2_receiver)
        as2message.build(
            payload,
            filename=original_filename,
            subject=partner.get("subject"),
            content_type=partner.get("content_type"),
            disposition_notification_to=org.get("email_address")
                                        or "no-reply@pyas2.com",
        )

    message, _ = await Message.objects.acreate_from_as2message(
        as2message=as2message,
        payload=payload,
        filename=original_filename,
        direction="OUT",
        status="P",
    )

    # Check if we're inside an atomic block, if not, commit immediately to store the message
    if not transaction.get_connection().in_atomic_block:
        await sync_to_async(transaction.commit)()  # Safe to commit if not in an atomic block

    await message.asend_message(as2message.headers, as2message.content)

    # Delete original file if option is set
    if options["delete"]:
        default_storage.delete(options["path_to_payload"])


class Command(BaseCommand):
    """Command to send an AS2 message."""

    help = "Send an as2 message to your trading partner"
    args = "<organization_as2name partner_as2name path_to_payload>"

    def add_arguments(self, parser):
        parser.add_argument("org_as2name", type=str)
        parser.add_argument("partner_as2name", type=str)
        parser.add_argument("path_to_payload", type=str)

        parser.add_argument(
            "--delete",
            action="store_true",
            dest="delete",
            default=False,
            help="Delete source file after processing",
        )

    def handle(self, *args, **options):
        asyncio.run(main(*args, **options))
