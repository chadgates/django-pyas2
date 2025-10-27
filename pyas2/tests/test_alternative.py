import os
from unittest import mock

from django.test import Client, TestCase
from pyas2lib import Message as As2Message

from pyas2.caching import clear_pyas2_cache
from pyas2.models import (
    Mdn,
    Message,
    Organization,
    Partner,
    Partnership,
    PrivateKey,
    PublicCertificate,
)
from pyas2.tests import TEST_DIR
from pyas2.tests.test_basic import SendMessageMock


class AlternativeCertTestCases(TestCase):
    """Test cases dealing with handling of failures and other features"""

    @classmethod
    def setUpTestData(cls):
        # Every test needs a client.
        cls.client = Client()

        # Load the client and server certificates
        with open(os.path.join(TEST_DIR, "server_private.pem"), "rb") as fp:
            cls.server_key = PrivateKey.objects.create(key=fp.read(), key_pass="test")

        with open(os.path.join(TEST_DIR, "server_public.pem"), "rb") as fp:
            cls.server_crt = PublicCertificate.objects.create(certificate=fp.read())

        with open(os.path.join(TEST_DIR, "client_private.pem"), "rb") as fp:
            cls.client_key = PrivateKey.objects.create(key=fp.read(), key_pass="test")

        with open(os.path.join(TEST_DIR, "client_public.pem"), "rb") as fp:
            cls.client_crt = PublicCertificate.objects.create(certificate=fp.read())

        with open(os.path.join(TEST_DIR, "server_alt_private.pem"), "rb") as fp:
            cls.server_alt_key = PrivateKey.objects.create(
                key=fp.read(), key_pass="test"
            )

        with open(os.path.join(TEST_DIR, "server_alt_public.pem"), "rb") as fp:
            cls.server_alt_crt = PublicCertificate.objects.create(certificate=fp.read())

    def setUp(self):

        # Setup the server organization and partner
        self.server_organization = Organization.objects.create(
            name="AS2 Server",
            as2_name="as2server",
            encryption_key=self.server_key,
            signature_key=self.server_key,
            encryption_key_alt=self.server_alt_key,
            signature_key_alt=self.server_alt_key,
        )
        self.partner = Partner.objects.create(
            name="AS2 Client",
            as2_name="as2client",
            target_url="http://localhost:8080/pyas2/as2receive",
            compress=False,
            mdn=False,
            signature_cert=self.client_crt,
            encryption_cert=self.client_crt,
        )

        # Setup the client organization and partner
        self.organization = Organization.objects.create(
            name="AS2 Client",
            as2_name="as2client",
            encryption_key=self.client_key,
            signature_key=self.client_key,
        )

        self.partnership = Partnership.objects.create(
            partner=self.partner,
            organization=self.server_organization,
            organization_key=Partnership.PRIMARY,
            organization_auto_swap=False,
        )

        # Initialise the payload i.e. the file to be transmitted
        with open(os.path.join(TEST_DIR, "testmessage.edi"), "rb") as fp:
            self.payload = fp.read()

    @classmethod
    def tearDownClass(cls):
        # remove all files in the inbox folders
        inbox = os.path.join("messages", "as2server", "inbox", "as2client")
        try:
            files = os.listdir(inbox)
        except OSError:
            files = []
        for the_file in files:
            file_path = os.path.join(inbox, the_file)
            if os.path.isfile(file_path):
                os.unlink(file_path)
        for message in Message.objects.all():
            message.headers.delete()
            message.payload.delete()
        for mdn in Mdn.objects.all():
            mdn.headers.delete()
            mdn.payload.delete()
        for partnership in Partnership.objects.all():
            partnership.delete()
        clear_pyas2_cache()

    def testAltKey(self):
        """Sender sends encrypted and signed data with alternative certificate.
        Alternate certificate used to decrypt the message.
        """
        partner = Partner.objects.create(
            name="AS2 Server",
            as2_name="as2server",
            target_url="http://localhost:8080/pyas2/as2receive",
            encryption="tripledes_192_cbc",
            encryption_cert=self.server_alt_crt,
            mdn=True,
            mdn_mode="SYNC",
            mdn_sign="sha1",
            signature_cert=self.server_alt_crt,
        )
        self.partnership.organization_auto_swap = False
        self.partnership.save()

        in_message = self.build_and_send(partner)

        # Check if message was processed successfully

        out_message = Message.objects.get(
            message_id=in_message.message_id, direction="IN"
        )
        self.assertEqual(out_message.status, "S")
        self.assertTrue(out_message.encrypted)
        self.assertEqual(in_message.status, "S")
        self.assertIsNotNone(in_message.mdn)
        self.assertTrue(in_message.mdn.signed)

    def testAltKeyAutoSwap(self):
        """Sender sends encrypted and signed data with alternative certificate.
        Alternate certificate used to decrypt the message and Partnership
        """
        partner = Partner.objects.create(
            name="AS2 Server",
            as2_name="as2server",
            target_url="http://localhost:8080/pyas2/as2receive",
            encryption="tripledes_192_cbc",
            encryption_cert=self.server_alt_crt,
            mdn=True,
            mdn_mode="SYNC",
            mdn_sign="sha1",
            signature_cert=self.server_alt_crt,
        )

        self.partnership.organization_auto_swap = True
        self.partnership.save()

        self.assertEqual(self.partnership.organization_key, Partnership.PRIMARY)
        in_message = self.build_and_send(partner)
        self.partnership.refresh_from_db()
        self.assertEqual(self.partnership.organization_key, Partnership.ALTERNATE)

        # Check if message was processed successfully

        out_message = Message.objects.get(
            message_id=in_message.message_id, direction="IN"
        )
        self.assertEqual(out_message.status, "S")
        self.assertTrue(out_message.encrypted)
        self.assertEqual(in_message.status, "S")
        self.assertIsNotNone(in_message.mdn)
        self.assertTrue(in_message.mdn.signed)

    def testSwitchOrgPartners(self):

        organization = Organization.objects.create(
            name="Organization",
            as2_name="as2organization",
            encryption_key=self.server_key,
            signature_key=self.server_key,
            encryption_key_alt=self.server_alt_key,
            signature_key_alt=self.server_alt_key,
        )
        partner_1 = Partner.objects.create(
            name="Partner1",
            as2_name="as2partner1",
            target_url="http://localhost:8080/pyas2/as2receive",
            compress=False,
            mdn=False,
            signature_cert=self.client_crt,
            encryption_cert=self.client_crt,
        )

        partner_2 = Partner.objects.create(
            name="Partner2",
            as2_name="as2partner2",
            target_url="http://localhost:8080/pyas2/as2receive",
            compress=False,
            mdn=False,
            signature_cert=self.client_crt,
            encryption_cert=self.client_crt,
        )

        partnership_1 = Partnership.objects.create(
            partner=partner_1,
            organization=organization,
            organization_key=Partnership.ALTERNATE,
            organization_auto_swap=False,
        )

        partnership_2 = Partnership.objects.create(
            partner=partner_2,
            organization=organization,
            organization_key=Partnership.PRIMARY,
            organization_auto_swap=False,
        )

        organization.swap_primary_alt()
        partnership_1.refresh_from_db()
        partnership_2.refresh_from_db()

        self.assertEqual(organization.encryption_key, self.server_alt_key)
        self.assertEqual(organization.signature_key, self.server_alt_key)
        self.assertEqual(organization.encryption_key_alt, self.server_key)
        self.assertEqual(organization.signature_key_alt, self.server_key)
        self.assertEqual(partnership_1.organization_key, Partnership.PRIMARY)
        self.assertEqual(partnership_2.organization_key, Partnership.ALTERNATE)

    @mock.patch("requests.post")
    def build_and_send(self, partner, mock_request, smudge=False):

        # Build and send the message to server
        as2message = As2Message(
            sender=self.organization.as2org, receiver=partner.as2partner
        )
        as2message.build(
            self.payload,
            filename="testmessage.edi",
            subject=partner.subject,
            content_type=partner.content_type,
        )
        out_message, _ = Message.objects.create_from_as2message(
            as2message=as2message, payload=self.payload, direction="OUT", status="P"
        )
        mock_request.side_effect = SendMessageMock(self.client)
        out_message.send_message(
            as2message.headers,
            b"xxxx" + as2message.content if smudge else as2message.content,
        )

        return out_message
