import hashlib
import threading

from django.core.cache import cache
from django.forms.models import model_to_dict

from pyas2.models import Organization, Partner, Partnership

# ------------------------------------
# Process-local cache for loaded AS2 objects
# ------------------------------------
# Private key parsing (load_pem_private_key) is expensive (~38ms per call with
# the cryptography backend). Since django-pyas2 creates new As2Organization /
# As2Partner objects on every request, this cost adds up fast.
#
# This in-process dict caches the constructed pyas2lib objects keyed by a hash
# of their constructor params. Each pod/process builds its own cache.
#
# Cross-pod invalidation: a version counter is stored in the shared Django cache
# (Redis/Memcached). When any pod updates keys/certs, it bumps the version.
# Other pods detect the version change on the next request and clear their
# local object cache. Cost: one cache.get() per request (~sub-ms for Redis).

AS2_OBJECT_CACHE_VERSION_KEY = "as2_object_cache_version"
_as2_object_cache = {}
_as2_object_cache_lock = threading.Lock()
_as2_object_cache_version = None


def _check_object_cache_version():
    """Check if the shared cache version has changed; if so, clear local cache."""
    global _as2_object_cache_version
    remote_version = cache.get(AS2_OBJECT_CACHE_VERSION_KEY)
    if remote_version != _as2_object_cache_version:
        with _as2_object_cache_lock:
            _as2_object_cache.clear()
            _as2_object_cache_version = remote_version


def _bump_object_cache_version():
    """Increment the shared version counter to invalidate all pods' local caches."""
    global _as2_object_cache_version
    try:
        new_version = cache.incr(AS2_OBJECT_CACHE_VERSION_KEY)
    except ValueError:
        # Key doesn't exist yet, initialize it
        cache.set(AS2_OBJECT_CACHE_VERSION_KEY, 1, None)
        new_version = 1
    with _as2_object_cache_lock:
        _as2_object_cache.clear()
        _as2_object_cache_version = new_version


def _params_cache_key(params):
    """Create a stable cache key from AS2 object params dict."""
    parts = []
    for k in sorted(params.keys()):
        v = params[k]
        if isinstance(v, bytes):
            parts.append(f"{k}:{hashlib.md5(v).hexdigest()}")
        else:
            parts.append(f"{k}:{v}")
    return "|".join(parts)


def get_cached_as2org(params):
    """Get or create a cached As2Organization from params."""
    from pyas2lib import Organization as As2Organization

    _check_object_cache_version()
    key = ("org", _params_cache_key(params))
    obj = _as2_object_cache.get(key)
    if obj is None:
        obj = As2Organization(**params)
        with _as2_object_cache_lock:
            _as2_object_cache[key] = obj
    return obj


def get_cached_as2partner(params):
    """Get or create a cached As2Partner from params."""
    from pyas2lib import Partner as As2Partner

    _check_object_cache_version()
    key = ("partner", _params_cache_key(params))
    obj = _as2_object_cache.get(key)
    if obj is None:
        obj = As2Partner(**params)
        with _as2_object_cache_lock:
            _as2_object_cache[key] = obj
    return obj


CACHE_TIMEOUT = 86400  # Cache duration in seconds
PARTNER_CACHE_KEY = "partner_cache"
ORGANIZATION_CACHE_KEY = "organization_cache"
PARTNERSHIP_CACHE_KEY = "partnership_cache"
PARTNERSHIP_CACHE_KEY_STATE = "partnership_cache_state"
LOADED = "loaded"

# Locks to prevent thundering herd on cache reload.
# When cache expires, only one thread reloads while others wait.
_partner_lock = threading.Lock()
_organization_lock = threading.Lock()
_partnership_lock = threading.Lock()

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
    cache.set(PARTNERSHIP_CACHE_KEY_STATE, LOADED, CACHE_TIMEOUT)
    return ps_data


def _reload_partners_if_needed(as2_name):
    """Reload partner cache under lock to prevent thundering herd."""
    with _partner_lock:
        result = cache.get("-".join([PARTNER_CACHE_KEY, as2_name]))
        if result is None:
            load_partner_cache()
            result = cache.get("-".join([PARTNER_CACHE_KEY, as2_name]))
    return result


def _reload_organizations_if_needed(as2_name):
    """Reload organization cache under lock to prevent thundering herd."""
    with _organization_lock:
        result = cache.get("-".join([ORGANIZATION_CACHE_KEY, as2_name]))
        if result is None:
            load_organization_cache()
            result = cache.get("-".join([ORGANIZATION_CACHE_KEY, as2_name]))
    return result


def _reload_partnerships_if_needed(org_as2_name, partner_as2_name):
    """Reload partnership cache under lock to prevent thundering herd."""
    with _partnership_lock:
        key = "-".join([PARTNERSHIP_CACHE_KEY, org_as2_name, partner_as2_name])
        result = cache.get(key)
        if result is None and cache.get(PARTNERSHIP_CACHE_KEY_STATE) != LOADED:
            load_partnership_cache()
            result = cache.get(key)
    return result


# ----------------------------
# Sync Cache Access Functions
# ----------------------------


def get_cached_partners():
    partners = cache.get(PARTNER_CACHE_KEY)
    if partners is None:
        partners = load_partner_cache()
    return partners


def get_cached_partners_by_as2_name(as2_name):
    if as2_name is None:
        return None
    partner = cache.get("-".join([PARTNER_CACHE_KEY, as2_name]))
    if partner is None:
        partner = _reload_partners_if_needed(as2_name)
    return partner


def get_cached_organizations():
    organizations = cache.get(ORGANIZATION_CACHE_KEY)
    if organizations is None:
        organizations = load_organization_cache()
    return organizations


def get_cached_organizations_by_as2_name(as2_name):
    if as2_name is None:
        return None
    org = cache.get("-".join([ORGANIZATION_CACHE_KEY, as2_name]))
    if org is None:
        org = _reload_organizations_if_needed(as2_name)
    return org


def get_cached_partnerships():
    partnerships = cache.get(PARTNERSHIP_CACHE_KEY)
    if partnerships is None:
        partnerships = load_partnership_cache()
    return partnerships


def get_cached_partnerships_by_as2_name(org_as2_name, partner_as2_name):
    if org_as2_name is None or partner_as2_name is None:
        return None

    partnership = cache.get(
        "-".join([PARTNERSHIP_CACHE_KEY, org_as2_name, partner_as2_name])
    )
    if partnership is None and cache.get(PARTNERSHIP_CACHE_KEY_STATE) != LOADED:
        partnership = _reload_partnerships_if_needed(org_as2_name, partner_as2_name)
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
    _bump_object_cache_version()
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
    _bump_object_cache_version()
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
    _bump_object_cache_version()
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
    _bump_object_cache_version()
    return partners


def delete_organization_from_cache(as2_name):
    """
    Delete a single Organization entry from the cache by its as2_name.
    """
    organizations = cache.get(ORGANIZATION_CACHE_KEY)
    if organizations and as2_name in organizations:
        del organizations[as2_name]
        cache.set(ORGANIZATION_CACHE_KEY, organizations, CACHE_TIMEOUT)
    _bump_object_cache_version()
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
    _bump_object_cache_version()
    return partnerships


def clear_pyas2_cache():
    cache.delete(PARTNER_CACHE_KEY)
    cache.delete(ORGANIZATION_CACHE_KEY)
    cache.delete(PARTNERSHIP_CACHE_KEY)
    _bump_object_cache_version()
