"""Transport behaviour.

Every test here covers a failure that is silent without the code under test.
None of them assert that a successful request succeeds — that case is covered
implicitly by every resource test and is not where the risk is.
"""

import unittest

from ..client import PopuliClient
from ..errors import (
    PopuliApiError,
    PopuliAuthError,
    PopuliIncompleteReadError,
    PopuliNotFoundError,
    PopuliPagingError,
    PopuliRateLimitError,
)
from .support import (
    FakeResponse,
    FakeSession,
    connection_error,
    error_body,
    list_body,
    timeout_error,
)


def make_client(responses, **kwargs):
    session = FakeSession(responses)
    slept = []
    client = PopuliClient(
        base_url='https://school.populiweb.com/api2/',
        access_key='sk_test',
        session=session,
        sleep=slept.append,
        **kwargs,
    )
    return client, session, slept


class ErrorDetection(unittest.TestCase):
    def test_error_object_under_http_200_raises(self):
        """The failure mode this client exists for.

        Populi returns error objects with a success status. Deserialized into a
        list response that yields an empty ``data`` array, which at the call
        site is indistinguishable from "no results".
        """
        client, _, _ = make_client([FakeResponse(200, error_body())])

        with self.assertRaises(PopuliApiError) as caught:
            client.get('people/1')

        error = caught.exception
        self.assertTrue(error.was_reported_with_success_status)
        self.assertEqual(error.populi_code, 400)
        self.assertEqual(error.populi_type, 'invalid_parameter')
        self.assertEqual(error.status_code, 200)

    def test_is_client_error_prefers_populi_code_over_http_status(self):
        """A 200 carrying ``code: 400`` is a rejected request, not a healthy one."""
        client, _, _ = make_client([FakeResponse(200, error_body(code=400))])

        with self.assertRaises(PopuliApiError) as caught:
            client.get('people/1')

        self.assertTrue(caught.exception.is_client_error)
        self.assertEqual(caught.exception.effective_code, 400)

    def test_transport_failure_has_no_status_code(self):
        """No response means no status to classify, and no client error."""
        client, _, _ = make_client([connection_error()], max_retries=0)

        with self.assertRaises(PopuliApiError) as caught:
            client.get('people/1')

        self.assertIsNone(caught.exception.status_code)
        self.assertFalse(caught.exception.is_client_error)

    def test_status_maps_to_specific_types(self):
        for status, expected in (
            (401, PopuliAuthError),
            (403, PopuliAuthError),
            (404, PopuliNotFoundError),
            (429, PopuliRateLimitError),
        ):
            with self.subTest(status=status):
                client, _, _ = make_client(
                    [FakeResponse(status, error_body(code=status))], max_retries=0
                )
                with self.assertRaises(expected):
                    client.get('people/1')

    def test_non_json_body_is_surfaced_not_swallowed(self):
        client, _, _ = make_client(
            [FakeResponse(502, text='<html>gateway</html>')], max_retries=0
        )

        with self.assertRaises(PopuliApiError) as caught:
            client.get('people/1')

        self.assertIn('gateway', caught.exception.raw_body)


class RetryPolicy(unittest.TestCase):
    def test_client_error_is_never_retried(self):
        """Resending an unchanged malformed request cannot answer differently."""
        client, session, _ = make_client([FakeResponse(400, error_body())])

        with self.assertRaises(PopuliApiError):
            client.get('people/1')

        self.assertEqual(len(session.calls), 1)

    def test_rate_limit_pauses_and_retries(self):
        client, session, slept = make_client(
            [FakeResponse(429, error_body(code=429)), FakeResponse(200, {'id': 1})]
        )

        self.assertEqual(client.get('people/1'), {'id': 1})
        self.assertEqual(len(session.calls), 2)
        # Just over a minute, per Populi's own instruction — not a short backoff.
        self.assertEqual(slept, [65])

    def test_rate_limit_honours_retry_after_when_present(self):
        client, _, slept = make_client(
            [
                FakeResponse(429, error_body(code=429), headers={'Retry-After': '90'}),
                FakeResponse(200, {'id': 1}),
            ]
        )

        client.get('people/1')
        self.assertEqual(slept, [90])

    def test_rate_limit_is_retried_even_for_a_write(self):
        """A 429 refused the request, so nothing was applied and replay is safe."""
        client, session, _ = make_client(
            [FakeResponse(429, error_body(code=429)), FakeResponse(200, {})]
        )

        client.post('people/1/notes', {'content': 'x'})
        self.assertEqual(len(session.calls), 2)

    def test_gateway_errors_retry_for_reads(self):
        client, session, _ = make_client(
            [FakeResponse(503, error_body(code=503)), FakeResponse(200, {'id': 1})]
        )

        client.get('people/1')
        self.assertEqual(len(session.calls), 2)

    def test_gateway_errors_do_not_retry_a_write(self):
        """A 503 may have applied the write; replaying could duplicate it."""
        client, session, _ = make_client([FakeResponse(503, error_body(code=503))])

        with self.assertRaises(PopuliApiError):
            client.post('people/1/custominfodata', {'value': 'x'})

        self.assertEqual(len(session.calls), 1)

    def test_plain_500_is_not_retried(self):
        """Not 'any 5xx' — a 500 is a fault a replay reproduces."""
        client, session, _ = make_client([FakeResponse(500, error_body(code=500))])

        with self.assertRaises(PopuliApiError):
            client.get('people/1')

        self.assertEqual(len(session.calls), 1)

    def test_transport_failure_replays_a_read(self):
        client, session, _ = make_client(
            [timeout_error(), FakeResponse(200, {'id': 1})]
        )

        client.get('people/1')
        self.assertEqual(len(session.calls), 2)

    def test_transport_failure_does_not_replay_a_write(self):
        """The write may have landed. Replaying creates a second data row."""
        client, session, _ = make_client([connection_error()])

        with self.assertRaises(PopuliApiError):
            client.post('people/1/custominfodata', {'value': 'x'})

        self.assertEqual(len(session.calls), 1)

    def test_write_declared_idempotent_is_replayed(self):
        client, session, _ = make_client(
            [connection_error(), FakeResponse(200, {})]
        )

        client.post('people/1/tags/add', {'tag_id': 5}, retry_safe=True)
        self.assertEqual(len(session.calls), 2)


class Paging(unittest.TestCase):
    def test_walks_every_page(self):
        client, _, _ = make_client(
            [
                FakeResponse(200, list_body([{'id': 1}], page=1, results=2, has_more=True)),
                FakeResponse(200, list_body([{'id': 2}], page=2, results=2)),
            ]
        )

        rows = client.list_all('people/1/tags')
        self.assertEqual([r['id'] for r in rows], [1, 2])

    def test_page_echo_mismatch_raises(self):
        """A paging parameter that never reaches Populi returns page 1 forever.

        That is indistinguishable from healthy paging without this check, and
        the rows pile up as duplicates.
        """
        client, _, _ = make_client(
            [
                FakeResponse(200, list_body([{'id': 1}], page=1, results=2, has_more=True)),
                FakeResponse(200, list_body([{'id': 1}], page=1, results=2, has_more=True)),
            ]
        )

        with self.assertRaises(PopuliPagingError):
            client.list_all('people/1/tags')

    def test_short_read_raises_rather_than_returning_a_partial_list(self):
        """A short read and 'nothing there' are the same empty list downstream."""
        client, _, _ = make_client(
            [FakeResponse(200, list_body([{'id': 1}], page=1, results=5))]
        )

        with self.assertRaises(PopuliIncompleteReadError) as caught:
            client.list_all('people/1/custominfodata')

        self.assertEqual(caught.exception.collected, 1)
        self.assertEqual(caught.exception.reported, 5)
        # Transient, not a rejected request — so it is worth retrying.
        self.assertFalse(caught.exception.is_client_error)

    def test_more_rows_than_reported_is_tolerated(self):
        """Rows added while paging cannot turn a present value into an absent one."""
        client, _, _ = make_client(
            [FakeResponse(200, list_body([{'id': 1}, {'id': 2}], page=1, results=1))]
        )

        self.assertEqual(len(client.list_all('people/1/tags')), 2)

    def test_empty_page_stops_the_loop_even_if_has_more_is_set(self):
        client, _, _ = make_client(
            [FakeResponse(200, list_body([], page=1, results=0, has_more=True))]
        )

        self.assertEqual(client.list_all('people/1/tags'), [])

    def test_non_list_shape_raises(self):
        client, _, _ = make_client([FakeResponse(200, {'object': 'person', 'id': 1})])

        with self.assertRaises(PopuliApiError):
            client.list_all('people/1')


class RequestShape(unittest.TestCase):
    def test_parameters_travel_in_the_json_body(self):
        client, session, _ = make_client(
            [FakeResponse(200, list_body([], page=1, results=0))]
        )

        client.list_all('people', {'filter': {'0': {}}})

        call = session.calls[0]
        self.assertEqual(call['method'], 'GET')
        self.assertIn('filter', call['json'])
        # limit and page are parameters like any other; a query-string form
        # would be silently dropped.
        self.assertEqual(call['json']['page'], 1)
        self.assertEqual(call['json']['limit'], 200)

    def test_authorization_header_is_a_bearer_token(self):
        client, session, _ = make_client([FakeResponse(200, {})])
        self.assertEqual(session.headers['Authorization'], 'Bearer sk_test')

    def test_empty_body_decodes_to_a_mapping(self):
        """Some write routes answer 200 with nothing; callers still read fields."""
        client, _, _ = make_client([FakeResponse(200)])
        self.assertEqual(client.post('people/1/tags/add', {}), {})


if __name__ == '__main__':
    unittest.main()
