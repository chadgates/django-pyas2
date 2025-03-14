from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from pyas2.caching import (
    delete_organization_from_cache,
    delete_partner_from_cache,
    delete_partnership_from_cache,
    update_organization_cache,
    update_partner_cache,
    update_partnership_cache,
)
from pyas2.models import Organization, Partner, Partnership

# ----------------------------
# Partner Signals
# ----------------------------


@receiver(post_save, sender=Partner)
def partner_saved(sender, instance, **kwargs):
    update_partner_cache(instance)


@receiver(post_delete, sender=Partner)
def partner_deleted(sender, instance, **kwargs):
    delete_partner_from_cache(instance.as2_name)


# ----------------------------
# Organization Signals
# ----------------------------


@receiver(post_save, sender=Organization)
def organization_saved(sender, instance, **kwargs):
    update_organization_cache(instance)


@receiver(post_delete, sender=Organization)
def organization_deleted(sender, instance, **kwargs):
    delete_organization_from_cache(instance.as2_name)


# ----------------------------
# Partnership Signals
# ----------------------------


@receiver(post_save, sender=Partnership)
def partnership_saved(sender, instance, **kwargs):
    update_partnership_cache(instance)


@receiver(post_delete, sender=Partnership)
def partnership_deleted(sender, instance, **kwargs):
    # Build the composite key from organization's and partner's as2_name
    delete_partnership_from_cache(
        instance.organization.as2_name, instance.partner.as2_name
    )
