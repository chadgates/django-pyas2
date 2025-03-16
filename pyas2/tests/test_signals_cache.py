import os

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.test import Client, TestCase

from pyas2.caching import (
    ORGANIZATION_CACHE_KEY,
    PARTNER_CACHE_KEY,
    PARTNERSHIP_CACHE_KEY,
)
from pyas2.models import (
    Organization,
    Partner,
    Partnership,
    PrivateKey,
    PublicCertificate,
)
from pyas2.tests import TEST_DIR

# ----------------------------
# Organization Tests
# ----------------------------


class OrganizationSignalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.client = Client()
        # Load keys/certificates for organization.
        with open(os.path.join(TEST_DIR, "server_private.pem"), "rb") as fp:
            cls.server_key = PrivateKey.objects.create(key=fp.read(), key_pass="test")
        with open(os.path.join(TEST_DIR, "server_public.pem"), "rb") as fp:
            cls.server_crt = PublicCertificate.objects.create(certificate=fp.read())

    def setUp(self):
        cache.delete(ORGANIZATION_CACHE_KEY)
        self.signal_received = False

        # Temporary handler to flag signal emission.
        def test_handler(sender, instance, **kwargs):
            self.signal_received = True

        post_save.connect(test_handler, sender=Organization)
        self.test_handler = test_handler

    def tearDown(self):
        post_save.disconnect(self.test_handler, sender=Organization)

    def test_organization_post_save_signal(self):
        Organization.objects.create(
            name="AS2 Server",
            as2_name="as2server",
            encryption_key=self.server_key,
            signature_key=self.server_key,
        )
        self.assertTrue(self.signal_received)


class OrganizationCacheTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.client = Client()
        with open(os.path.join(TEST_DIR, "server_private.pem"), "rb") as fp:
            cls.server_key = PrivateKey.objects.create(key=fp.read(), key_pass="test")
        with open(os.path.join(TEST_DIR, "server_public.pem"), "rb") as fp:
            cls.server_crt = PublicCertificate.objects.create(certificate=fp.read())

    def setUp(self):
        cache.delete(ORGANIZATION_CACHE_KEY)
        # Ensure signal registration.
        from pyas2 import signals

    def test_organization_cache_update_on_create(self):
        org = Organization.objects.create(
            name="AS2 Server",
            as2_name="as2server",
            encryption_key=self.server_key,
            signature_key=self.server_key,
        )
        org_cache = cache.get(ORGANIZATION_CACHE_KEY)
        self.assertIsNotNone(org_cache)
        self.assertIn(org.as2_name, org_cache)

    def test_organization_cache_update_on_update(self):
        # Create the organization.
        org = Organization.objects.create(
            name="AS2 Server",
            as2_name="as2server",
            encryption_key=self.server_key,
            signature_key=self.server_key,
        )
        # Update a field that is cached. For instance, change the "name" field.
        org.name = "AS2 Server Updated"
        org.save()

        # Retrieve the updated cache.
        org_cache = cache.get(ORGANIZATION_CACHE_KEY)
        self.assertIsNotNone(org_cache)
        self.assertIn(org.as2_name, org_cache)
        # Verify the cache now has the updated "name".
        self.assertEqual(org_cache[org.as2_name]["name"], "AS2 Server Updated")

    def test_organization_cache_delete_on_delete(self):
        # Create an organization first.
        org = Organization.objects.create(
            name="AS2 Server",
            as2_name="as2server",
            encryption_key=self.server_key,
            signature_key=self.server_key,
        )
        # Confirm it's in the cache.
        org_cache = cache.get(ORGANIZATION_CACHE_KEY)
        self.assertIn(org.as2_name, org_cache)
        # Now delete it.
        org.delete()
        org_cache_after = cache.get(ORGANIZATION_CACHE_KEY)
        # Depending on your implementation the cache may be updated or fully cleared.
        self.assertNotIn(org.as2_name, org_cache_after)


# ----------------------------
# Partner Tests
# ----------------------------


class PartnerSignalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.client = Client()
        # Load a certificate for partner.
        with open(os.path.join(TEST_DIR, "server_public.pem"), "rb") as fp:
            cls.server_crt = PublicCertificate.objects.create(certificate=fp.read())

    def setUp(self):
        cache.delete(PARTNER_CACHE_KEY)
        self.signal_received = False

        def test_handler(sender, instance, **kwargs):
            self.signal_received = True

        post_save.connect(test_handler, sender=Partner)
        self.test_handler = test_handler

    def tearDown(self):
        post_save.disconnect(self.test_handler, sender=Partner)

    def test_partner_post_save_signal(self):
        Partner.objects.create(
            name="Partner 1",
            as2_name="partner1",
            encryption_cert=self.server_crt,
            signature_cert=self.server_crt,
        )
        self.assertTrue(self.signal_received)


class PartnerCacheTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.client = Client()
        with open(os.path.join(TEST_DIR, "server_public.pem"), "rb") as fp:
            cls.server_crt = PublicCertificate.objects.create(certificate=fp.read())

    def setUp(self):
        cache.delete(PARTNER_CACHE_KEY)
        from pyas2 import signals

    def test_partner_cache_update_on_create(self):
        partner = Partner.objects.create(
            name="Partner 1",
            as2_name="partner1",
            encryption_cert=self.server_crt,
            signature_cert=self.server_crt,
        )
        partner_cache = cache.get(PARTNER_CACHE_KEY)
        self.assertIsNotNone(partner_cache)
        self.assertIn(partner.as2_name, partner_cache)

    def test_partner_cache_update_on_update(self):
        partner = Partner.objects.create(
            name="Partner 1",
            as2_name="partner1",
            encryption_cert=self.server_crt,
            signature_cert=self.server_crt,
        )
        # Update the partner's name.
        partner.name = "Partner 1 Updated"
        partner.save()

        partner_cache = cache.get(PARTNER_CACHE_KEY)
        self.assertIsNotNone(partner_cache)
        self.assertIn(partner.as2_name, partner_cache)
        self.assertEqual(partner_cache[partner.as2_name]["name"], "Partner 1 Updated")

    def test_partner_cache_delete_on_delete(self):
        partner = Partner.objects.create(
            name="Partner 1",
            as2_name="partner1",
            encryption_cert=self.server_crt,
            signature_cert=self.server_crt,
        )
        partner_cache = cache.get(PARTNER_CACHE_KEY)
        self.assertIn(partner.as2_name, partner_cache)
        partner.delete()
        partner_cache_after = cache.get(PARTNER_CACHE_KEY)
        self.assertNotIn(partner.as2_name, partner_cache_after)


# ----------------------------
# Partnership Tests (Signal and Cache)
# ----------------------------


class PartnershipSignalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.client = Client()
        with open(os.path.join(TEST_DIR, "server_private.pem"), "rb") as fp:
            cls.server_key = PrivateKey.objects.create(key=fp.read(), key_pass="test")
        with open(os.path.join(TEST_DIR, "server_public.pem"), "rb") as fp:
            cls.server_crt = PublicCertificate.objects.create(certificate=fp.read())

        # Create Organization and Partner for the Partnership.
        cls.org = Organization.objects.create(
            name="AS2 Server",
            as2_name="as2server",
            encryption_key=cls.server_key,
            signature_key=cls.server_key,
        )
        cls.partner = Partner.objects.create(
            name="Partner 1",
            as2_name="partner1",
            encryption_cert=cls.server_crt,
            signature_cert=cls.server_crt,
        )

    def setUp(self):
        cache.delete(PARTNERSHIP_CACHE_KEY)
        self.signal_saved_received = False
        self.signal_deleted_received = False

        def test_saved_handler(sender, instance, **kwargs):
            self.signal_saved_received = True

        def test_deleted_handler(sender, instance, **kwargs):
            self.signal_deleted_received = True

        post_save.connect(test_saved_handler, sender=Partnership)
        post_delete.connect(test_deleted_handler, sender=Partnership)
        self.test_saved_handler = test_saved_handler
        self.test_deleted_handler = test_deleted_handler

    def tearDown(self):
        post_save.disconnect(self.test_saved_handler, sender=Partnership)
        post_delete.disconnect(self.test_deleted_handler, sender=Partnership)

    def test_partnership_post_save_signal(self):
        Partnership.objects.create(
            organization=self.org,
            partner=self.partner,
        )
        self.assertTrue(self.signal_saved_received)

    def test_partnership_post_delete_signal(self):
        partnership = Partnership.objects.create(
            organization=self.org,
            partner=self.partner,
        )
        # Reset flag and then delete.
        self.signal_deleted_received = False
        partnership.delete()
        self.assertTrue(self.signal_deleted_received)


class PartnershipCacheTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.client = Client()
        with open(os.path.join(TEST_DIR, "server_private.pem"), "rb") as fp:
            cls.server_key = PrivateKey.objects.create(key=fp.read(), key_pass="test")
        with open(os.path.join(TEST_DIR, "server_public.pem"), "rb") as fp:
            cls.server_crt = PublicCertificate.objects.create(certificate=fp.read())
        with open(os.path.join(TEST_DIR, "server_alt_private.pem"), "rb") as fp:
            cls.server_alt_key = PrivateKey.objects.create(
                key=fp.read(), key_pass="test"
            )
        cls.org = Organization.objects.create(
            name="AS2 Server",
            as2_name="as2server",
            encryption_key=cls.server_key,
            signature_key=cls.server_key,
            encryption_key_alt=cls.server_alt_key,
            signature_key_alt=cls.server_alt_key,
        )
        cls.partner = Partner.objects.create(
            name="Partner 1",
            as2_name="partner1",
            encryption_cert=cls.server_crt,
            signature_cert=cls.server_crt,
        )

    def setUp(self):
        # Clear the partnership cache.
        cache.delete(PARTNERSHIP_CACHE_KEY)
        # Ensure that the partnership cache is rebuilt.

    def test_partnership_cache_update_on_create(self):
        Partnership.objects.create(
            organization=self.org,
            partner=self.partner,
            organization_key=Partnership.PRIMARY,
        )
        partnership_cache = cache.get(PARTNERSHIP_CACHE_KEY)
        key = "-".join([self.org.as2_name, self.partner.as2_name])
        self.assertIsNotNone(partnership_cache)
        self.assertIn(key, partnership_cache)

    def test_partnership_cache_update_on_update(self):
        # Create a partnership with an initial email address.
        partnership = Partnership.objects.create(
            organization=self.org,
            partner=self.partner,
            organization_key=Partnership.PRIMARY,
        )
        key = "-".join([self.org.as2_name, self.partner.as2_name])
        partnership_cache = cache.get(PARTNERSHIP_CACHE_KEY)
        self.assertIsNotNone(partnership_cache)
        self.assertIn(key, partnership_cache)
        self.assertEqual(
            partnership_cache[key].get("organization_key"), partnership.PRIMARY
        )

        # Now update the partnership's email address.
        partnership.organization_key = Partnership.ALTERNATE
        partnership.save()

        # Retrieve the cache and check the update.
        updated_cache = cache.get(PARTNERSHIP_CACHE_KEY)
        self.assertEqual(
            updated_cache[key].get("organization_key"), partnership.ALTERNATE
        )

    def test_partnership_cache_delete_on_delete(self):
        partnership = Partnership.objects.create(
            organization=self.org,
            partner=self.partner,
        )
        key = "-".join([self.org.as2_name, self.partner.as2_name])
        partnership_cache = cache.get(PARTNERSHIP_CACHE_KEY)
        self.assertIn(key, partnership_cache)
        partnership.delete()
        partnership_cache_after = cache.get(PARTNERSHIP_CACHE_KEY)
        self.assertNotIn(key, partnership_cache_after)
