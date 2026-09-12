"""Notes on a person's profile.

This is the API2 home of the legacy ``addActivityFeedNote``, and that mapping is
**proven rather than inferred**. ``GET /people/4605662/notes`` returns a note
dated 2024-03-25 whose content is::

    #🔰 Background Check Status#

    Completed, with results ✅

which is byte-for-byte what ``Person.add_note_to_activity_feed`` composes, and
which was written through the legacy ``addActivityFeedNote``. A legacy activity
feed note is readable as an API2 note, so the two names describe one object.
``/notes`` is also the only note-creating surface in the API.
"""

import logging

logger = logging.getLogger(__name__)


class Notes:
    """Read and add notes on a person."""

    def __init__(self, client):
        self._client = client

    def list(self, person_id):
        return self._client.list_all('people/%s/notes' % person_id)

    def create(self, person_id, content):
        """Add a note to a person's profile.

        **The write parameter is ``note``; the read field is ``content``.** They
        are not the same word, and nothing in the reference says so — sending
        ``content`` is answered with
        ``Missing required parameter: note``. Measured against the live instance
        after every Background Check note silently failed: the unit test had
        asserted ``{'content': ...}``, which proved only that the client sent
        what the client intended to send.

        Returns the created note. Not verified by re-reading: unlike a custom
        field there is no prior value to compare against, and unlike a tag there
        is no duplicate-detection to lean on — a second identical note is a
        second note, so a retry-and-check loop here would create duplicates
        rather than confirm anything.
        """
        return self._client.post(
            'people/%s/notes' % person_id, {'note': content}
        )
