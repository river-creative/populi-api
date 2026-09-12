"""Academic terms."""


class AcademicTerms:
    """Read the term catalogue."""

    def __init__(self, client):
        self._client = client

    def list(self):
        """Every academic term, oldest first as Populi returns them."""
        return self._client.list_all('academicterms')

    def get(self, term_id):
        return self._client.get('academicterms/%s' % term_id)

    def current(self):
        """The term Populi considers current, or None.

        A dedicated route rather than a date comparison against the list: terms
        overlap, and "current" is Populi's judgement to make, not arithmetic on
        start and end dates.
        """
        return self._client.get('academicterms/current') or None
