from django.core.cache import cache
from django.forms.models import model_to_dict

from pyas2.models import Organization, Partner, Partnership

CACHE_TIMEOUT = 86400  # Cache duration in seconds
PARTNER_CACHE_KEY = "partner_cache"
ORGANIZATION_CACHE_KEY = "organization_cache"
PARTNERSHIP_CACHE_KEY = "partnership_cache"


# ----------------------------
# Initial Cache Loading Functions
# ----------------------------


def load_partner_cache():
    partners_qs = Partner.objects.select_related(
        "encryption_cert", "signature_cert"
    ).all()
    partner_data = {}
    for partner in partners_qs:
        data = model_to_dict(partner)
        data["as2partner_params"] = partner.as2partner_params
        partner_data[partner.as2_name] = data
        cache.set("-".join([PARTNER_CACHE_KEY, partner.as2_name]), data, CACHE_TIMEOUT)
    cache.set(PARTNER_CACHE_KEY, partner_data, CACHE_TIMEOUT)
    return partner_data


def load_organization_cache():
    orgs_qs = Organization.objects.select_related(
        "encryption_key", "signature_key", "encryption_key_alt", "signature_key_alt"
    ).all()
    org_data = {}
    for org in orgs_qs:
        data = model_to_dict(org)
        data["as2org_params"] = org.as2org_params
        data["has_primary_and_alt_keys"] = org.has_primary_and_alt_keys
        data["as2orgalt_params"] = (
            org.as2orgalt_params if org.has_primary_and_alt_keys else None
        )
        org_data[org.as2_name] = data
        cache.set("-".join([ORGANIZATION_CACHE_KEY, org.as2_name]), data, CACHE_TIMEOUT)
    cache.set(ORGANIZATION_CACHE_KEY, org_data, CACHE_TIMEOUT)
    return org_data


def load_partnership_cache():
    partnership_qs = Partnership.objects.select_related(
        "partner",
        "organization",
        "organization__signature_key",
        "organization__signature_key_alt",
        "organization__encryption_key",
        "organization__encryption_key_alt",
    ).all()
    ps_data = {}
    for partnership in partnership_qs:
        try:
            data = model_to_dict(partnership)
            data["as2org_params"] = partnership.as2org_params
            data["email_address"] = partnership.email_address
            data["as2partner_params"] = partnership.partner.as2partner_params
            key = "-".join(
                [partnership.organization.as2_name, partnership.partner.as2_name]
            )
            ps_data[key] = data
            cache.set("-".join([PARTNERSHIP_CACHE_KEY, key]), data, CACHE_TIMEOUT)
        except AttributeError:
            # Skip if partnership has missing key attributes.
            continue
    cache.set(PARTNERSHIP_CACHE_KEY, ps_data, CACHE_TIMEOUT)
    return ps_data


def get_cached_partners():
    partners = cache.get(PARTNER_CACHE_KEY)
    if partners is None:
        partners = load_partner_cache()
    return partners

def get_cached_partners_by_as2_name(as2_name):
    partner = cache.get("-".join([PARTNER_CACHE_KEY, as2_name]))
    if partner is None:
        load_partner_cache()
        partner = cache.get("-".join([PARTNER_CACHE_KEY, as2_name]))
    return partner

def get_cached_organizations():
    organizations = cache.get(ORGANIZATION_CACHE_KEY)
    if organizations is None:
        organizations = load_organization_cache()
    return organizations

def get_cached_organizations_by_as2_name(as2_name):
    org = cache.get("-".join([ORGANIZATION_CACHE_KEY, as2_name]))
    if org is None:
        load_organization_cache()
        org = cache.get("-".join([ORGANIZATION_CACHE_KEY, as2_name]))
    return org


def get_cached_partnerships():
    partnerships = cache.get(PARTNERSHIP_CACHE_KEY)
    if partnerships is None:
        partnerships = load_partnership_cache()
    return partnerships

def get_cached_partnerships_by_as2_name(org_as2_name, partner_as2_name):
    partnership = cache.get("-".join([PARTNERSHIP_CACHE_KEY, org_as2_name, partner_as2_name]))
    if partnership is None:
        load_partnership_cache()
        partnership = cache.get("-".join([PARTNERSHIP_CACHE_KEY, org_as2_name, partner_as2_name]))
    return partnership

# ----------------------------
# Individual Update Functions
# ----------------------------


def update_partner_cache(partner):
    """
    Update (or add) a single Partner entry in the cache.
    """
    partners = cache.get(PARTNER_CACHE_KEY) or load_partner_cache()
    data = model_to_dict(partner)
    data["as2partner_params"] = partner.as2partner_params
    partners[partner.as2_name] = data
    cache.set(PARTNER_CACHE_KEY, partners, CACHE_TIMEOUT)
    cache.set("-".join([PARTNER_CACHE_KEY, partner.as2_name]), data, CACHE_TIMEOUT)
    return partners


def update_organization_cache(org):
    """
    Update (or add) a single Organization entry in the cache.
    """
    organizations = cache.get(ORGANIZATION_CACHE_KEY) or load_organization_cache()
    data = model_to_dict(org)
    data["as2org_params"] = org.as2org_params
    data["has_primary_and_alt_keys"] = org.has_primary_and_alt_keys
    data["as2orgalt_params"] = (
        org.as2orgalt_params if org.has_primary_and_alt_keys else None
    )
    organizations[org.as2_name] = data
    cache.set(ORGANIZATION_CACHE_KEY, organizations, CACHE_TIMEOUT)
    cache.set("-".join([ORGANIZATION_CACHE_KEY, org.as2_name]), data, CACHE_TIMEOUT)
    return organizations


def update_partnership_cache(partnership):
    """
    Update (or add) a single Partnership entry in the cache.
    """
    partnerships = cache.get(PARTNERSHIP_CACHE_KEY) or load_partnership_cache()
    try:
        data = model_to_dict(partnership)
        data["as2org_params"] = partnership.as2org_params
        data["email_address"] = partnership.email_address
        data["as2partner_params"] = partnership.partner.as2partner_params
        key = "-".join(
            [partnership.organization.as2_name, partnership.partner.as2_name]
        )
        partnerships[key] = data
        cache.set(PARTNERSHIP_CACHE_KEY, partnerships, CACHE_TIMEOUT)
        cache.set("-".join([PARTNERSHIP_CACHE_KEY, key]), data, CACHE_TIMEOUT)
    except AttributeError:
        pass
    return partnerships


# ----------------------------
# Individual Delete Functions
# ----------------------------


def delete_partner_from_cache(as2_name):
    """
    Delete a single Partner entry from the cache by its as2_name.
    """
    partners = cache.get(PARTNER_CACHE_KEY)
    if partners and as2_name in partners:
        del partners[as2_name]
        cache.set(PARTNER_CACHE_KEY, partners, CACHE_TIMEOUT)
    return partners


def delete_organization_from_cache(as2_name):
    """
    Delete a single Organization entry from the cache by its as2_name.
    """
    organizations = cache.get(ORGANIZATION_CACHE_KEY)
    if organizations and as2_name in organizations:
        del organizations[as2_name]
        cache.set(ORGANIZATION_CACHE_KEY, organizations, CACHE_TIMEOUT)
    return organizations


def delete_partnership_from_cache(org_as2_name, partner_as2_name):
    """
    Delete a single Partnership entry from the cache by combining
    the organization's and partner's as2_name.
    """
    partnerships = cache.get(PARTNERSHIP_CACHE_KEY)
    if partnerships:
        key = "-".join([org_as2_name, partner_as2_name])
        if key in partnerships:
            del partnerships[key]
            cache.set(PARTNERSHIP_CACHE_KEY, partnerships, CACHE_TIMEOUT)
    return partnerships


def clear_pyas2_cache():
    cache.delete(PARTNER_CACHE_KEY)
    cache.delete(ORGANIZATION_CACHE_KEY)
    cache.delete(PARTNERSHIP_CACHE_KEY)
