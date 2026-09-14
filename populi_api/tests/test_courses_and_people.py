"""Grades, bulk person lookups, and term-scoped custom info data.

Every test here covers a documented-nowhere behaviour that a reasonable
implementation gets wrong.
"""

import unittest

from .. import Populi
from ..client import PopuliClient
from ..errors import PopuliApiError
from ..resources.custom_fields import term_data_path
from .support import FakeResponse, FakeSession, error_body, list_body


def make(responses):
    session = FakeSession(responses)
    client = PopuliClient(
        base_url='https://school.populiweb.com/api2/',
        access_key='sk_test',
        session=session,
        sleep=lambda _: None,
    )
    return Populi(client), session


class Grades(unittest.TestCase):
    """Points in, percent out — and excusing is a grade, not a flag."""

    def test_set_grade_sends_points(self):
        populi, session = make([FakeResponse(200, {'grade': 100})])

        populi.courses.set_grade(10, 20, 30, points=1)

        call = session.calls[0]
        self.assertEqual(call['method'], 'PUT')
        self.assertTrue(call['url'].endswith(
            'courseofferings/10/assignments/20/students/30/grade/update'))
        self.assertEqual(call['json'], {'grade': 1})

    def test_excuse_sends_the_grade_E_not_a_flag(self):
        """The route accepts an `excused` parameter, returns 200, and ignores it."""
        populi, session = make([FakeResponse(200, {'grade': 0, 'excused': True})])

        populi.courses.excuse(10, 20, 30)

        self.assertEqual(session.calls[0]['json'], {'grade': 'E'})
        self.assertNotIn('excused', session.calls[0]['json'])

    def test_clearing_sends_an_empty_grade(self):
        populi, session = make([FakeResponse(200, {})])
        populi.courses.clear_grade(10, 20, 30)
        self.assertEqual(session.calls[0]['json'], {'grade': ''})

    def test_none_is_refused_before_sending(self):
        """Populi answers null with a 400, and the caller meant one of two things."""
        populi, session = make([])

        with self.assertRaises(PopuliApiError):
            populi.courses.set_grade(10, 20, 30, points=None)

        self.assertEqual(session.calls, [])

    def test_an_ungraded_student_is_an_empty_object_not_a_404(self):
        populi, _ = make([FakeResponse(200, {})])
        self.assertEqual(populi.courses.grade(10, 20, 30), {})


class BulkPeople(unittest.TestCase):
    def test_rows_that_do_not_match_the_filter_are_discarded(self):
        """A filter Populi cannot read is dropped and everyone comes back.

        Without the client-side re-check that is indistinguishable from a
        correct answer, and the caller acts on strangers.
        """
        populi, _ = make([FakeResponse(200, list_body([
            {'id': 1, 'student': {'visible_student_id': '101'}},
            {'id': 2, 'student': {'visible_student_id': '999'}},   # not asked for
        ], results=2))])

        found = populi.people.by_student_ids(['101'])

        self.assertEqual([p['id'] for p in found], [1])

    def test_ids_are_chunked(self):
        """A large id filter is truncated silently, so it is split."""
        pages = [FakeResponse(200, list_body([], results=0)) for _ in range(4)]
        populi, session = make(pages)

        populi.people.by_student_ids([str(n) for n in range(120)])

        self.assertGreaterEqual(len(session.calls), 3)

    def test_update_with_no_fields_is_refused(self):
        populi, session = make([])

        with self.assertRaises(PopuliApiError):
            populi.people.update(1, {})

        self.assertEqual(session.calls, [])


class TermScopedData(unittest.TestCase):
    def test_the_route_is_keyed_on_the_term(self):
        """Not on a field id, and not under the student scope."""
        self.assertEqual(term_data_path(1, 55), 'people/1/custominfodata/term/55')
        self.assertEqual(term_data_path(1, 55, 99), 'people/1/custominfodata/term/55/99')

    def test_update_addresses_the_data_row(self):
        populi, session = make([FakeResponse(200, {})])

        populi.custom_fields.update_term_value(1, 55, 99, 'x')

        self.assertTrue(session.calls[0]['url'].endswith(
            'people/1/custominfodata/term/55/99'))
        self.assertEqual(session.calls[0]['json'], {'value': 'x'})

    def test_values_can_be_narrowed_to_one_field(self):
        populi, _ = make([FakeResponse(200, list_body([
            {'id': 1, 'custom_info_field_id': 900010, 'value': 'a'},
            {'id': 2, 'custom_info_field_id': 900020, 'value': 'b'},
        ], results=2))])

        rows = populi.custom_fields.term_values(1, 55, field_id=900010)
        self.assertEqual([r['id'] for r in rows], [1])


class FieldDefinitions(unittest.TestCase):
    def test_a_dropped_options_expand_raises_rather_than_reading_as_empty(self):
        """Populi ignores an expand it does not recognise and still answers 200.

        A missing options key then means "not honoured", never "this field has
        none" — and treating it as none reads an empty catalogue as fact.
        """
        populi, _ = make([FakeResponse(200, {
            'object': 'custom_info_field', 'id': 900010, 'input_type': 'checkbox',
        })])

        with self.assertRaises(PopuliApiError) as caught:
            populi.custom_fields.definition(900010, 'admissions', include_options=True)

        self.assertEqual(caught.exception.populi_type, 'expand_dropped')

    def test_options_are_returned_when_honoured(self):
        populi, _ = make([FakeResponse(200, {
            'object': 'custom_info_field', 'id': 900010, 'input_type': 'checkbox',
            'options': [{'id': 1, 'name': 'A', 'retired': False}],
        })])

        field = populi.custom_fields.definition(900010, 'admissions', include_options=True)
        self.assertEqual(len(field['options']), 1)

    def test_the_show_route_carries_no_trailing_slash(self):
        """One route, one spelling.

        This call was the only one in the client written with a trailing slash,
        and it is the spelling that has never been driven against a live
        instance — the unslashed one has. Nothing asserted the URL, so the two
        forms coexisted silently. Asserting it is what keeps a future edit from
        reintroducing the coin flip.
        """
        populi, session = make([FakeResponse(200, {
            'object': 'custom_info_field', 'id': 900010, 'input_type': 'checkbox',
            'options': [],
        })])

        populi.custom_fields.definition(900010, 'admissions', include_options=True)

        url = session.calls[0]['url']
        self.assertTrue(url.endswith('admissionscustominfofields/900010'), url)


class Connection(unittest.TestCase):
    def test_test_connection_raises_rather_than_returning_false(self):
        """Four different problems, and a bare False makes them one."""
        populi, _ = make([FakeResponse(401, error_body(code=401, message='bad key'))])

        with self.assertRaises(PopuliApiError):
            populi.test_connection()

    def test_test_connection_is_true_when_it_works(self):
        populi, _ = make([FakeResponse(200, list_body([{'id': 1}], results=1))])
        self.assertTrue(populi.test_connection())


if __name__ == '__main__':
    unittest.main()
