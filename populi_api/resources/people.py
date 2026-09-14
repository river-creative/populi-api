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

# Populi truncates a large id filter silently, so bulk lookups are chunked.
MAX_IDS_PER_FILTER = 50

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

    def get(self, person_id):
        """One person by their Populi id, or None."""
        try:
            return self._client.get('people/%s' % person_id)
        except PopuliNotFoundError:
            return None

    def list(self, filter=None, expand=None, modified_since=None):
        """Every person matching a filter.

        ``filter`` accepts a :class:`populi_api.filters.PopuliFilter` or the raw
        envelope. With no filter this walks the whole directory — tens of
        thousands of people — so pass one unless that is genuinely the intent.

        **Confirm a new filter actually narrowed the result.** Populi discards a
        condition it cannot read and answers 200 with everyone, so a filtered
        read returning more than expected has not failed — it has been ignored.
        """
        parameters = {}
        if filter is not None:
            parameters['filter'] = filter.to_dict() if hasattr(filter, 'to_dict') else filter
        if expand:
            parameters['expand'] = list(expand)
        if modified_since:
            parameters['modified_since'] = modified_since

        return self._client.list_all('people', parameters or None)

    def by_student_ids(self, student_ids, expand=None):
        """Several people by visible student id, in as few requests as possible.

        **Every row is re-checked against the ids asked for.** This is a
        filtered read, and a filter Populi cannot read is discarded rather than
        rejected — so without the client-side check a widened filter returns
        strangers and nothing about the response looks wrong.

        Chunked because a large id filter is truncated silently. 50 is the
        figure a sibling project settled on; measure before raising it, and
        measure by planting known-real ids at the END of the group, or a row
        count tells you nothing.
        """
        from ..filters import PopuliFilter

        wanted = [str(s) for s in student_ids]
        found = []

        for start in range(0, len(wanted), MAX_IDS_PER_FILTER):
            chunk = wanted[start:start + MAX_IDS_PER_FILTER]

            built = PopuliFilter().any_of()
            for student_id in chunk:
                built.where('student_id', {'type': 'EQUALS', 'text': student_id})

            parameters = {
                'filter': built.to_dict(),
                'expand': list(expand) if expand else ['student'],
            }

            for person in self._client.list_all('people', parameters):
                student = person.get('student') or {}
                if str(student.get('visible_student_id')) in chunk:
                    found.append(person)
                else:
                    logger.warning(
                        'populi returned person %s for a student_id filter they do '
                        'not match; the filter was widened or dropped',
                        person.get('id'),
                    )

        return found

    # Walks every page: `with_role` on a large role such as Student is
    # thousands of people and dozens of requests against a 50/min budget shared
    # with everything else using this key. Reach for it when you genuinely want
    # the whole set, and pace the caller if you do.
    def with_role(self, role_id, status='ACTIVE'):
        """Everyone holding a role.

        Role ids are instance-specific — resolve them from ``GET /roles`` rather
        than hardcoding a name, which is not stable across instances.
        """
        from ..filters import PopuliFilter

        built = PopuliFilter().all_of().where(
            'role', {'role_id': str(role_id), 'status': status}
        )
        return self._client.list_all('people', {'filter': built.to_dict()})

    def update(self, person_id, fields):
        """Change fields on a person. Partial — only the keys given are sent."""
        if not fields:
            raise PopuliApiError(
                'update called with no fields; nothing would change',
                status_code=400,
                endpoint='people/%s' % person_id,
                populi_type='invalid_parameter',
            )

        return self._client.put('people/%s' % person_id, dict(fields))

    def online_payment_link(self, person_id):
        """A time-limited link for a student to pay online, or None.

        Verified shape: ``{"object": ..., "person_id": ..., "url": ...}``. The
        legacy equivalent was documented as good for 30 days; nothing in API2
        restates that, so callers should treat it as short-lived and not cache
        it.
        """
        body = self._client.get('people/%s/onlinepaymentlink' % person_id)
        return body.get('url') or None
