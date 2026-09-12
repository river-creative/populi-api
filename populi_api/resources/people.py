"""Person lookups.

``by_student_id`` replaces the legacy ``searchPeople``, and the replacement is a
correctness fix rather than a port. The legacy call searched by free text and
returned candidates, leaving the caller to pick one — and Populi's search-style
lookups fail OPEN, returning the whole directory when they cannot read a
condition rather than erroring. A dedicated route that takes a student id and
answers with one person removes that failure mode entirely.

Verified against the live instance: ``GET /people/by_student_id`` with
``{"student_id": "101"}`` returns a single person **object**, not a list.
"""

import logging

from ..errors import PopuliApiError, PopuliNotFoundError

logger = logging.getLogger(__name__)


class People:
    """Look up people and their payment links."""

    def __init__(self, client):
        self._client = client

    def by_student_id(self, student_id):
        """The person holding this visible student id, or None.

        Returns ``None`` rather than raising when nobody matches: at every call
        site "no such student" is an expected answer that gets its own branch,
        not an exceptional condition.

        The shape is asserted rather than assumed. If this route ever starts
        answering with a list — which is what a lookup that stopped
        understanding its parameter would most plausibly do — that is a silent
        change of meaning, and picking ``[0]`` from it would hand back an
        arbitrary stranger. Raising is the only safe response.
        """
        try:
            person = self._client.get(
                'people/by_student_id', {'student_id': str(student_id)}
            )
        except PopuliNotFoundError:
            return None

        if not person:
            return None

        if person.get('object') == 'list':
            raise PopuliApiError(
                'by_student_id answered with a list rather than a person; the '
                'route contract has changed and picking one row would be a guess',
                status_code=200,
                endpoint='people/by_student_id',
            )

        return person

    def online_payment_link(self, person_id):
        """A time-limited link for a student to pay online, or None.

        Verified shape: ``{"object": ..., "person_id": ..., "url": ...}``. The
        legacy equivalent was documented as good for 30 days; nothing in API2
        restates that, so callers should treat it as short-lived and not cache
        it.
        """
        body = self._client.get('people/%s/onlinepaymentlink' % person_id)
        return body.get('url') or None
