"""Person tag operations.

Both behaviours in this module are the opposite of what the official reference
documents, and both were measured against a live instance rather than inferred.
They are the single most expensive pair of mistakes available in this API,
because the wrong form of each *looks like success*.
"""

import logging

from ..errors import PopuliApiError

logger = logging.getLogger(__name__)

# Populi's refusal to add a tag twice. This is not a failure: it is the
# authoritative confirmation that the tag is on the person, and it is the only
# reliable one -- see the note on verification below.
ALREADY_ADDED_MESSAGE = 'tag already added'


class Tags:
    """Add and remove a person's tags."""

    def __init__(self, client):
        self._client = client

    def list(self, person_id):
        """Every tag currently on a person.

        Beware using this to confirm a write — see ``add``.
        """
        return self._client.list_all('people/%s/tags' % person_id)

    def add(self, person_id, tag_id):
        """Put a tag on a person. Returns True if it is now there.

        **POST with a JSON body, not the documented GET.** Measured against a
        live instance: ``GET .../tags/add`` with the id in the body returns
        HTTP 200 and the person's tag list, and adds nothing — it reads as a
        successful call. The same request as a query string returns 400. Only
        POST with a body actually works.

        **The result is deliberately not confirmed by re-reading.**
        ``GET /people/{id}/tags`` lags an add by *minutes* — measured still
        showing the pre-write list at t+60s — so a confirming read reports a
        landed write as failed. The lag is asymmetric: removes appear within
        seconds, which is what makes it so easy to mis-model, because a
        round-trip test that unticks first will "prove" the index is live.
        """
        try:
            self._client.post(
                'people/%s/tags/add' % person_id,
                {'tag_id': tag_id},
                # A duplicate add is answered with "Tag already added" and
                # changes nothing, so replaying this one is provably harmless.
                retry_safe=True,
            )
            return True
        except PopuliApiError as exc:
            if self._is_already_added(exc):
                logger.debug(
                    'populi tag %s already on person %s', tag_id, person_id
                )
                return True
            raise

    def remove(self, person_id, tag_id):
        """Take a tag off a person.

        POST for the same reason as ``add``. The reference documents a GET here
        too, and a GET with a body was observed to work for remove specifically
        — but relying on that would mean the pair behaves differently for no
        reason a reader could infer, so both use the form that is known good.

        A tag that was not there is not an error: the desired end state holds
        either way.
        """
        try:
            self._client.post(
                'people/%s/tags/remove' % person_id,
                {'tag_id': tag_id},
                retry_safe=True,
            )
            return True
        except PopuliApiError as exc:
            if exc.effective_code == 404:
                logger.debug(
                    'populi tag %s was not on person %s', tag_id, person_id
                )
                return True
            raise

    @staticmethod
    def _is_already_added(exc):
        return bool(exc.message) and ALREADY_ADDED_MESSAGE in exc.message.lower()
