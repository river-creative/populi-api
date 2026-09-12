"""Data Slicer reports — the bulk-export escape hatch.

For a wide, arbitrary column set, including custom fields, a report built in
Populi's UI is pulled in one call. That is far cheaper than N per-person reads
when many people are needed at once, and it is the intended answer to "I need
thirty columns about four hundred students".

**These are HEAVY calls and cannot run concurrently.** One at a time, per
Populi. The pacer spaces requests but does not serialise them, so do not fan
these out.

Custom field columns come back named ``custom_field_<fieldId>_<index>``.
"""

import logging

logger = logging.getLogger(__name__)


class DataSlicer:
    """List the available reports and pull their results."""

    def __init__(self, client):
        self._client = client

    def reports(self):
        """Every Data Slicer report defined in this instance."""
        return self._client.list_all('dataslicerreports')

    def results(self, report_id, page=1, export_format='JSON'):
        """One page of a report's results.

        Paged like any other list route, but deliberately NOT walked
        automatically: a Data Slicer report can be enormous, it cannot run
        concurrently, and pulling every page without the caller asking is how
        one convenience call becomes a multi-minute stall holding the key's
        whole budget.
        """
        return self._client.post(
            'dataslicerreports/%s/results' % report_id,
            {'export_format': export_format, 'page': page},
            # A report run has no side effects, so replaying one after a lost
            # response is safe — unlike most POSTs.
            retry_safe=True,
        )

    def all_results(self, report_id, export_format='JSON', max_pages=100):
        """Every page of a report, walked in order.

        Bounded by ``max_pages`` because the stop condition here is a short
        page rather than a ``has_more`` flag, and an unbounded loop against a
        heavy route is the wrong kind of mistake to leave available.
        """
        rows = []
        for page in range(1, max_pages + 1):
            body = self.results(report_id, page=page, export_format=export_format)
            data = body.get('data') or body.get('results') or []
            if not data:
                break
            rows.extend(data)
            if not body.get('has_more'):
                break
        else:
            logger.warning(
                'data slicer report %s stopped at the %d page ceiling; there may '
                'be more', report_id, max_pages,
            )

        return rows
