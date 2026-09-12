"""Communication plan instances attached to a person.

The legacy ``deleteCommunicationPlanFromPerson`` took the instance id and the
person id in that order, which is the reverse of how the API2 path reads
(``/people/{person}/communicationplans/{instance}``). The argument order is the
kind of detail that ports silently wrong, so this module takes them in path
order and the call sites are updated to match.
"""

import logging

from ..errors import PopuliNotFoundError

logger = logging.getLogger(__name__)


class CommunicationPlans:
    """Read and detach a person's communication plans."""

    def __init__(self, client):
        self._client = client

    def list(self, person_id):
        """Every communication plan instance attached to a person.

        An empty list is the normal case for most people; the legacy caller
        treated a null response as "nothing to do" and that behaviour carries
        over unchanged.
        """
        return self._client.list_all('people/%s/communicationplans' % person_id)

    def delete(self, person_id, instance_id):
        """Detach one plan instance. Returns False if it was already gone.

        Already-gone is not a fault: the desired end state holds either way, and
        these are removed in response to webhooks that can arrive more than once.
        """
        try:
            self._client.delete(
                'people/%s/communicationplans/%s' % (person_id, instance_id)
            )
        except PopuliNotFoundError:
            logger.debug(
                'populi communication plan %s already detached from person %s',
                instance_id, person_id,
            )
            return False

        return True
