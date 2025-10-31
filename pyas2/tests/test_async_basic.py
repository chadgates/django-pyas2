"""
Async tests for the AS2 server and client.
These tests verify that the async views work correctly in an async context.
"""

import os
from email.parser import HeaderParser

import pytest
from django.test import AsyncClient
from pyas2lib.as2 import Mdn as As2Mdn
from pyas2lib.as2 import Message as As2Message

from pyas2.caching import clear_pyas2_cache
from pyas2.models import (
    Mdn,
    Message,
    Organization,
    Partner,
    PrivateKey,
    PublicCertificate,
)
from pyas2.tests import TEST_DIR


@pytest.mark.asyncio
class TestAsyncAS2Views:
    """Test async AS2 views"""

    @pytest.fixture(autouse=True)
    async def setup(self):
        """Set up test data"""
        self.client = AsyncClient()
        self.header_parser = HeaderParser()

        # Load the client and server certificates
        with open(os.path.join(TEST_DIR, "server_private.pem"), "rb") as fp:
            self.server_key = await PrivateKey.objects.acreate(
                key=fp.read(), key_pass="test"
            )

        with open(os.path.join(TEST_DIR, "server_public.pem"), "rb") as fp:
            self.server_crt = await PublicCertificate.objects.acreate(
                certificate=fp.read()
            )

        with open(os.path.join(TEST_DIR, "client_private.pem"), "rb") as fp:
            self.client_key = await PrivateKey.objects.acreate(
                key=fp.read(), key_pass="test"
            )

        with open(os.path.join(TEST_DIR, "client_public.pem"), "rb") as fp:
            self.client_crt = await PublicCertificate.objects.acreate(
                certificate=fp.read()
            )

        # Setup the server organization and partner
        await Organization.objects.acreate(
            name="AS2 Server",
            as2_name="as2server",
            encryption_key=self.server_key,
            signature_key=self.server_key,
        )
        await Partner.objects.acreate(
            name="AS2 Client",
            as2_name="as2client",
            target_url="http://localhost:8080/pyas2/as2receive",
            compress=False,
            mdn=False,
            signature_cert=self.client_crt,
            encryption_cert=self.client_crt,
        )

        # Setup the client organization and partner
        self.organization = await Organization.objects.acreate(
            name="AS2 Client",
            as2_name="as2client",
            encryption_key=self.client_key,
            signature_key=self.client_key,
        )

        # Initialize the payload i.e. the file to be transmitted
        with open(os.path.join(TEST_DIR, "testmessage.edi"), "rb") as fp:
            self.payload = fp.read()

        yield

        # Cleanup
        inbox = os.path.join("messages", "as2server", "inbox", "as2client")
        if os.path.exists(inbox):
            for the_file in os.listdir(inbox):
                file_path = os.path.join(inbox, the_file)
                if os.path.isfile(file_path):
                    os.unlink(file_path)

        # Delete files using sync_to_async wrapper for file operations
        from asgiref.sync import sync_to_async

        async for message in Message.objects.all():
            if message.headers:
                await sync_to_async(message.headers.delete)()
            if message.payload:
                await sync_to_async(message.payload.delete)()

        async for mdn in Mdn.objects.all():
            if mdn.headers:
                await sync_to_async(mdn.headers.delete)()
            if mdn.payload:
                await sync_to_async(mdn.payload.delete)()

        clear_pyas2_cache()

    async def build_and_send_async(self, partner):
        """Build and send an AS2 message"""
        # Get partner and org for building message
        org_obj = await Organization.objects.select_related(
            "encryption_key", "signature_key"
        ).aget(as2_name="as2client")
        partner_obj = await Partner.objects.select_related(
            "encryption_cert", "signature_cert"
        ).aget(as2_name=partner.as2_name)

        # Build the AS2 message
        as2message = As2Message(
            sender=org_obj.as2org,
            receiver=partner_obj.as2partner,
        )
        as2message.build(
            self.payload,
            filename="testmessage.edi",
            subject=partner_obj.subject,
            content_type=partner_obj.content_type,
        )

        # Create the message object
        message, _ = await Message.objects.acreate_from_as2message(
            as2message=as2message,
            payload=self.payload,
            filename="testmessage.edi",
            direction="OUT",
            status="P",
        )

        # Post the message to the server
        response = await self.client.post(
            "/pyas2/as2receive/",
            data=as2message.content,
            content_type=as2message.headers.get("content-type")
            or "application/octet-stream",
            **{
                f"HTTP_{k.upper().replace('-', '_')}": v
                for k, v in as2message.headers.items()
            },
        )

        # Parse the response if it's an MDN
        if response.status_code == 200 and response.content:
            try:
                # Refresh message from database to get as2message property
                # Note: Filter by direction="OUT" since the server creates an "IN" message
                #       with same ID
                message = await Message.objects.select_related(
                    "organization", "partner"
                ).aget(message_id=message.message_id, direction="OUT")

                # Build properly formatted MDN content (following models.py:561-569 pattern)
                mdn_headers = dict(
                    (k.lower().replace("_", "-"), v)
                    for k, v in response.headers.items()
                )
                mdn_content = (
                    f'message-id: {mdn_headers.get("message-id", message.message_id)}\n'
                )
                mdn_content += (
                    f'content-type: {mdn_headers.get("content-type", "")}\n\n'
                )
                mdn_content = mdn_content.encode("utf-8") + response.content

                # Parse the AS2 MDN (parse is sync, so wrap it)
                from asgiref.sync import sync_to_async

                as2mdn = As2Mdn()
                as2message = await message.aget_as2message()
                status, detailed_status = await as2mdn.aparse(
                    mdn_content, lambda x, y: as2message
                )

                if detailed_status != "mdn-not-found":
                    await Mdn.objects.acreate_from_as2mdn(
                        as2mdn=as2mdn, message=message, status="R"
                    )
                    message.status = "S" if status == "processed" else "E"
                    await message.asave()
            except Exception as e:
                # Log the exception for debugging
                import traceback

                print(f"Failed to parse MDN: {e}")
                traceback.print_exc()

        return message

    def compare_files(self, file1, file2):
        """Compare two files using Django storage"""
        from django.core.files.storage import default_storage
        with default_storage.open(file1, "rb") as f1, default_storage.open(file2, "rb") as f2:
            return f1.read() == f2.read()

    async def test_async_endpoint(self):
        """Test if the as2 receive endpoint is active in async mode"""
        response = await self.client.get("/pyas2/as2receive/")
        assert response.status_code == 200

    async def test_async_no_encrypt_message_no_mdn(self):
        """Test async: Sender sends un-encrypted data and does NOT request a receipt."""
        # Create the partner with appropriate settings for this case
        partner = await Partner.objects.acreate(
            name="AS2 Server",
            as2_name="as2server",
            target_url="http://localhost:8080/pyas2/as2receive",
            mdn=False,
        )
        in_message = await self.build_and_send_async(partner)

        # Check if message was processed successfully
        out_message = await Message.objects.aget(
            message_id=in_message.message_id, direction="IN"
        )
        assert out_message.status == "S"

        # Check if input and output files are the same
        assert self.compare_files(in_message.payload.name, out_message.payload.name)

    async def test_async_no_encrypt_message_mdn(self):
        """Test async: Sender sends un-encrypted data and requests an unsigned receipt."""
        # Create the partner with appropriate settings for this case
        partner = await Partner.objects.acreate(
            name="AS2 Server",
            as2_name="as2server",
            target_url="http://localhost:8080/pyas2/as2receive",
            mdn=True,
            mdn_mode="SYNC",
        )
        in_message = await self.build_and_send_async(partner)

        # Check if message was processed successfully
        out_message = await Message.objects.aget(
            message_id=in_message.message_id, direction="IN"
        )
        assert out_message.status == "S"
        assert in_message.status == "S"

        # Check if MDN exists
        assert await Mdn.objects.filter(message=in_message).aexists()
        mdn = await Mdn.objects.aget(message=in_message)
        assert not mdn.signed

        # Check if input and output files are the same
        assert self.compare_files(in_message.payload.name, out_message.payload.name)

    async def test_async_options_request(self):
        """Test async: OPTIONS request to the as2receive endpoint"""
        response = await self.client.options("/pyas2/as2receive/")
        assert response.status_code == 200
        assert "POST" in response["allow"]
        assert "GET" in response["allow"]
