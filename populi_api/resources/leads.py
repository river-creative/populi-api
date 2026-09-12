"""Admissions lead reads and status updates.

The legacy ``setLeadInfo`` took a person id and a status and worked out which
lead it meant. API2 updates a specific lead:
``PUT /people/{person}/leads/{lead}``. So a status change is now "find the
lead, then update it", and *which* lead is a decision this module has to make
explicitly rather than inherit.

Verified against the live instance: ``GET /people/1001/leads`` returns rows
carrying ``id``, ``status`` (e.g. ``'accepted'``), ``active``, ``most_recent``
and ``person_id``.
"""

import logging
import re

from ..errors import PopuliConfigurationError

logger = logging.getLogger(__name__)


class LeadStatus:
    """The status vocabulary, measured from live data rather than assumed.

    The legacy API took these UPPERCASE — ``setLeadInfo(person, "CONFIRMED")``.
    API2 uses lowercase snake_case, confirmed by sampling 200 live leads:
    inquiry, prospect, application_started, application_completed, accepted,
    confirmed, enrolled.

    That difference is invisible at the call site and would have broken every
    lead automation in this project, which is why these are constants rather
    than string literals sprinkled through the controllers.

    Not an exhaustive list: 200 of 31,552 leads were sampled, so a rare status
    may be missing. Nothing validates against this set for that reason — see
    ``Leads.set_status`` for the guard that is safe to apply.
    """

    INQUIRY = 'inquiry'
    PROSPECT = 'prospect'
    APPLICATION_STARTED = 'application_started'
    APPLICATION_COMPLETED = 'application_completed'
    ACCEPTED = 'accepted'
    CONFIRMED = 'confirmed'
    ENROLLED = 'enrolled'


# Every observed status is lowercase letters and underscores. Checking the
# SHAPE rather than membership of a list catches the uppercase mistake — the
# one that would actually have been made here — without rejecting a status
# Populi adds later, which a closed allowlist would.
_STATUS_SHAPE = re.compile(r'^[a-z][a-z_]*$')


class Leads:
    """Read a person's leads and move their status."""

    def __init__(self, client):
        self._client = client

    def list(self, person_id):
        """Every lead attached to a person, newest information included."""
        return self._client.list_all('people/%s/leads' % person_id)

    def current(self, person_id):
        """The lead a status change should apply to, or None.

        Prefers an active lead, then the one Populi marks ``most_recent``, then
        the first returned. ``None`` means the person has no lead at all — which
        for this application means a current student rather than an applicant,
        and is a case callers branch on rather than an error.

        The preference order is explicit because the legacy API chose for us and
        that choice is now ours to make. Picking blindly — ``leads[0]`` — would
        quietly write to a stale lead on anyone who has more than one.
        """
        leads = self.list(person_id)
        if not leads:
            return None

        for lead in leads:
            if lead.get('active'):
                return lead

        for lead in leads:
            if lead.get('most_recent'):
                return lead

        logger.debug(
            'populi person %s has %d lead(s), none active or most_recent; '
            'using the first', person_id, len(leads),
        )
        return leads[0]

    def current_status(self, person_id):
        """The status of the lead a change would apply to, or None."""
        lead = self.current(person_id)
        return lead.get('status') if lead else None

    def set_status(self, person_id, status, lead_id=None):
        """Move a person's lead to ``status``. Returns False if they have none.

        ``lead_id`` may be supplied when the caller already resolved it, saving
        a request against a budget this application can exhaust.

        Rejects an uppercase status before sending it. The legacy API's
        vocabulary was uppercase and this one's is not, so every ported call
        site is one careless copy away from sending a value Populi will not
        recognise — and a rejected status change is the kind of failure this
        application swallows and logs rather than surfacing.
        """
        if not _STATUS_SHAPE.match(str(status)):
            raise PopuliConfigurationError(
                'lead status %r is not in API2 form; it uses lowercase '
                'snake_case (e.g. %r), unlike the legacy API which took '
                'uppercase' % (status, LeadStatus.CONFIRMED)
            )

        if lead_id is None:
            lead = self.current(person_id)
            if lead is None:
                logger.debug(
                    'populi person %s has no lead; not setting status %s',
                    person_id, status,
                )
                return False
            lead_id = lead['id']

        self._client.put(
            'people/%s/leads/%s' % (person_id, lead_id), {'status': status}
        )
        return True
