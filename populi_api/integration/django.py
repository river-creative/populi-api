"""Builds a configured ``Populi`` from Django settings.

The only module in this package that imports Django. Everything it does is read
settings and pass them to a constructor, which is the whole reason the client
proper can be lifted into its own repository later without touching its call
sites.

**The client is a process-wide singleton, and that is load-bearing rather than
an optimisation.** Populi's request budget belongs to the API *key*, shared by
every caller using it. A pacer created per request paces nothing — each one
starts with an empty schedule and fires immediately, so N concurrent webhooks
make N simultaneous requests no matter what interval is configured. One shared
instance is what makes the interval mean anything.
"""

import threading

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .. import Populi, PopuliClient
from ..errors import PopuliConfigurationError
from ..pacing import Pacer

# Share of the key's budget this application claims. Not 1.0: the budget is
# shared with anything else using the same key — an ad-hoc script, a report, a
# person waiting on an interactive lookup — and provisioning one webhook worker
# to consume the entire allowance is how the others start seeing 429s.
DEFAULT_UTILISATION = 0.8

_lock = threading.Lock()
_populi = None


def get_populi():
    """The shared, paced Populi client for this process.

    Built on first use rather than at import, so a missing setting surfaces as
    an ``ImproperlyConfigured`` from the code that needed it rather than as an
    import error during ``collectstatic``.
    """
    global _populi

    if _populi is not None:
        return _populi

    with _lock:
        # Re-checked inside the lock: two threads can pass the check above.
        if _populi is None:
            _populi = _build()

    return _populi


def reset():
    """Drop the cached client. For tests, and for a settings change at runtime."""
    global _populi
    with _lock:
        _populi = None


def _build():
    base_url = _required('POPULI_BASE_URL')
    access_key = _required('POPULI_ACCESS_KEY')
    utilisation = getattr(settings, 'POPULI_PACING_UTILISATION', DEFAULT_UTILISATION)

    try:
        client = PopuliClient(
            base_url=base_url,
            access_key=access_key,
            pacer=Pacer(utilisation=utilisation),
        )
    except PopuliConfigurationError as exc:
        # Re-raised as Django's own type so a misconfiguration is reported the
        # same way as every other bad setting in this project, rather than as a
        # library-specific exception a reader has to look up.
        raise ImproperlyConfigured('Populi client misconfigured: %s' % exc) from exc

    return Populi(client)


def _required(name):
    value = getattr(settings, name, None)
    if not value:
        # Fail fast and name the setting. The failure this client exists to fix
        # was a valid key pointed at the wrong API, which produced an
        # authentication error on every call for weeks without anyone noticing;
        # a configuration problem should be unmissable at the point of use.
        raise ImproperlyConfigured(
            'settings.%s is required for the Populi integration' % name
        )
    return value
