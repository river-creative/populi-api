"""Resource behaviour.

Concentrated on the places where API2 differs from the legacy API in meaning
rather than in spelling, because those are the mappings a port gets wrong
silently.
"""

import unittest

from .. import Populi
from ..client import PopuliClient
from ..errors import PopuliApiError, PopuliConfigurationError
from ..resources.custom_fields import CustomFields, data_path, field_definition_path
from ..resources.leads import LeadStatus
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


class Tags(unittest.TestCase):
    def test_add_uses_post_with_a_body(self):
        """The documented GET returns 200 and the tag list, and adds nothing."""
        populi, session = make([FakeResponse(200, {})])

        populi.tags.add(4605662, 471893)

        call = session.calls[0]
        self.assertEqual(call['method'], 'POST')
        self.assertTrue(call['url'].endswith('people/4605662/tags/add'))
        self.assertEqual(call['json'], {'tag_id': 471893})

    def test_already_added_is_success_not_failure(self):
        """Populi's refusal to add twice is the authoritative 'it is there'.

        The tags index lags an add by minutes, so this 400 is the only
        trustworthy confirmation available.
        """
        populi, _ = make(
            [FakeResponse(400, error_body(code=400, message='Tag already added'))]
        )

        self.assertTrue(populi.tags.add(4605662, 471893))

    def test_a_different_400_still_raises(self):
        populi, _ = make(
            [FakeResponse(400, error_body(code=400, message='Please enter a valid tag'))]
        )

        with self.assertRaises(PopuliApiError):
            populi.tags.add(4605662, 999)

    def test_removing_a_tag_that_is_absent_is_not_an_error(self):
        populi, _ = make([FakeResponse(404, error_body(code=404, message='not found'))])

        self.assertTrue(populi.tags.remove(4605662, 471893))


def row(row_id, field_id, value):
    return {'id': row_id, 'custom_info_field_id': field_id, 'value': str(value)}


class FakeDefinitions:
    """Field definitions without a lookup request.

    Real ones are cached per scope; the tests care about what the client does
    with the answer, not about fetching it.
    """

    def __init__(self, input_type='checkbox', known=True):
        self._input_type = input_type
        self._known = known

    def get(self, field_id, scope):
        return {'input_type': self._input_type} if self._known else None

    def is_multi_value(self, field_id, scope):
        if not self._known:
            raise PopuliApiError(
                'unknown field', status_code=404, populi_type='object_not_found'
            )
        return self._input_type == 'checkbox'


def custom_fields(responses, input_type='checkbox', known=True):
    session = FakeSession(responses)
    client = PopuliClient(
        base_url='https://school.populiweb.com/api2/',
        access_key='sk_test',
        session=session,
        sleep=lambda _: None,
    )
    return CustomFields(client, FakeDefinitions(input_type, known)), session


class Scoping(unittest.TestCase):
    """Ten of twelve fields this app uses are `admissions`, not `person`.

    Reading the wrong scope returns NO rows rather than erroring, and callers
    treat absence as "not set" and then write — so the scope is what stands
    between an automation and silently overwriting live data.
    """

    def test_person_scope_is_the_bare_path(self):
        self.assertEqual(data_path(1, 'person'), 'people/1/custominfodata')
        self.assertEqual(data_path(1, None), 'people/1/custominfodata')

    def test_other_scopes_are_appended_without_underscores(self):
        self.assertEqual(data_path(1, 'admissions'), 'people/1/custominfodata/admissions')
        self.assertEqual(data_path(1, 'campus_life'), 'people/1/custominfodata/campuslife')

    def test_row_id_is_appended_after_the_scope(self):
        self.assertEqual(
            data_path(1, 'admissions', 99), 'people/1/custominfodata/admissions/99'
        )
        self.assertEqual(data_path(1, 'person', 99), 'people/1/custominfodata/99')

    def test_definition_routes_have_no_person_special_case(self):
        """The data routes nest person values bare; the definition routes do not.

        Sharing the data transform would request /custominfofields, which is a
        different thing entirely.
        """
        self.assertEqual(field_definition_path('person'), 'personcustominfofields')
        self.assertEqual(field_definition_path('admissions'), 'admissionscustominfofields')
        self.assertEqual(field_definition_path('term_student'), 'termstudentcustominfofields')


class CustomFieldWrites(unittest.TestCase):
    """A checkbox write REPLACES the whole selection — measured on the live API.

    POSTing one option id to a field holding three left ONE row, not four. So
    every checkbox write sends the complete array, and "add one" reads first.
    """

    def test_add_option_posts_the_whole_set_not_just_the_new_one(self):
        existing = [row(11, 212516, 458238), row(22, 212516, 458620)]
        fields, session = custom_fields(
            [
                FakeResponse(200, list_body(existing, results=2)),   # read current
                FakeResponse(200, {}),                               # write
                FakeResponse(200, list_body(                          # verify
                    existing + [row(33, 212516, 458237)], results=3
                )),
            ]
        )

        fields.add_option(4605662, 212516, 'admissions', 458237)

        write = session.calls[1]
        self.assertEqual(write['method'], 'POST')
        self.assertTrue(write['url'].endswith('people/4605662/custominfodata/admissions'))
        # The complete set. Posting just 458237 would leave it the ONLY option.
        self.assertEqual(
            sorted(write['json']['value']), sorted(['458238', '458620', '458237'])
        )

    def test_a_single_existing_option_is_still_preserved(self):
        """The exact case the C# client's `Count > 1` heuristic misses.

        Measured: a scalar write to a checkbox holding one option destroyed it.
        Keying on input_type rather than row count is what avoids that.
        """
        fields, session = custom_fields(
            [
                FakeResponse(200, list_body([row(11, 212516, 458238)], results=1)),
                FakeResponse(200, {}),
                FakeResponse(200, list_body(
                    [row(11, 212516, 458238), row(22, 212516, 458237)], results=2
                )),
            ]
        )

        fields.add_option(4605662, 212516, 'admissions', 458237)

        self.assertEqual(
            sorted(session.calls[1]['json']['value']), sorted(['458238', '458237'])
        )

    def test_add_option_already_present_writes_nothing(self):
        fields, session = custom_fields(
            [FakeResponse(200, list_body([row(11, 212516, 458237)], results=1))]
        )

        self.assertFalse(fields.add_option(4605662, 212516, 'admissions', 458237))
        self.assertEqual(len(session.calls), 1)

    def test_remove_option_posts_the_remaining_set(self):
        fields, session = custom_fields(
            [
                FakeResponse(200, list_body(
                    [row(11, 212516, 458238), row(22, 212516, 458237)], results=2
                )),
                FakeResponse(200, {}),
                FakeResponse(200, list_body([row(11, 212516, 458238)], results=1)),
            ]
        )

        fields.remove_option(4605662, 212516, 'admissions', 458237)

        self.assertEqual(session.calls[1]['json']['value'], ['458238'])

    def test_removing_the_last_option_deletes_the_rows(self):
        """An empty array is not a documented way to clear a field."""
        fields, session = custom_fields(
            [
                FakeResponse(200, list_body([row(11, 212516, 458237)], results=1)),
                FakeResponse(200, list_body([row(11, 212516, 458237)], results=1)),
                FakeResponse(200, {}),
            ]
        )

        fields.remove_option(4605662, 212516, 'admissions', 458237)

        deletes = [c for c in session.calls if c['method'] == 'DELETE']
        self.assertEqual(len(deletes), 1)
        self.assertTrue(deletes[0]['url'].endswith('custominfodata/admissions/11'))

    def test_a_single_valued_field_posts_a_scalar(self):
        fields, session = custom_fields(
            [
                # A single-valued write does not read first -- it replaces.
                FakeResponse(200, {}),                                # write
                FakeResponse(200, list_body([row(1, 212554, 458576)], results=1)),
            ],
            input_type='select',
        )

        fields.set_value(4605662, 212554, 'admissions', 458576)

        # The write is the FIRST call here: a single-valued field replaces
        # outright, so nothing is read beforehand.
        self.assertEqual(session.calls[0]['json']['value'], 458576)

    def test_several_values_on_a_single_valued_field_is_refused(self):
        fields, session = custom_fields([], input_type='radio')

        with self.assertRaises(PopuliApiError):
            fields.set_options(4605662, 212510, 'admissions', [1, 2])

        self.assertEqual(session.calls, [])

    def test_an_unknown_field_in_that_scope_raises(self):
        """A field id in the wrong scope is a configuration error, not a blank."""
        fields, _ = custom_fields(
            [FakeResponse(200, list_body([], results=0))], known=False
        )

        with self.assertRaises(PopuliApiError):
            fields.set_value(4605662, 999999, 'admissions', 'x')

    def test_delete_removes_every_row_in_the_right_scope(self):
        fields, session = custom_fields(
            [
                FakeResponse(200, list_body(
                    [row(11, 212516, 458238), row(22, 212516, 458237)], results=2
                )),
                FakeResponse(200, {}),
                FakeResponse(200, {}),
            ]
        )

        self.assertTrue(fields.delete(4605662, 212516, 'admissions'))

        deletes = [c for c in session.calls if c['method'] == 'DELETE']
        self.assertEqual(len(deletes), 2)
        for call in deletes:
            self.assertIn('/custominfodata/admissions/', call['url'])

    def test_a_write_that_does_not_land_raises(self):
        fields, _ = custom_fields(
            [
                FakeResponse(200, {}),                                # write
                FakeResponse(200, list_body([], results=0)),          # still absent
            ],
            input_type='select',
        )

        with self.assertRaises(PopuliApiError) as caught:
            fields.set_value(4605662, 212554, 'admissions', 'x')

        self.assertEqual(caught.exception.populi_type, 'write_not_applied')

    def test_a_write_verified_by_its_label_is_accepted(self):
        """An option field takes a label in and reports the id out.

        Writing "In Progress" to a radio stores the option whose label that is,
        and reads back as its id. Comparing ids only calls that a failed write —
        measured, it turned every application status update into a logged error
        and a notification email while the value was correctly set.
        """
        fields, _ = custom_fields(
            [
                FakeResponse(200, {}),                                # write
                FakeResponse(200, list_body([{                        # verify
                    'id': 1, 'custom_info_field_id': 212510,
                    'value': '458178', 'option_value': 'In Progress',
                }], results=1)),
            ],
            input_type='radio',
        )

        # Must not raise: the label written is the label stored.
        self.assertTrue(
            fields.set_value(4605662, 212510, 'admissions', 'In Progress')
        )

    def test_a_write_that_lands_as_neither_id_nor_label_still_raises(self):
        fields, _ = custom_fields(
            [
                FakeResponse(200, {}),
                FakeResponse(200, list_body([{
                    'id': 1, 'custom_info_field_id': 212510,
                    'value': '999999', 'option_value': 'Something Else',
                }], results=1)),
            ],
            input_type='radio',
        )

        with self.assertRaises(PopuliApiError):
            fields.set_value(4605662, 212510, 'admissions', 'In Progress')

    def test_get_values_returns_every_selected_option(self):
        fields, _ = custom_fields(
            [FakeResponse(200, list_body(
                [row(11, 212516, 458238), row(22, 212516, 458237)], results=2
            ))]
        )

        self.assertEqual(
            fields.get_values(4605662, 212516, 'admissions'), ['458238', '458237']
        )


class People(unittest.TestCase):
    def test_by_student_id_returns_the_person(self):
        populi, session = make([FakeResponse(200, {'object': 'person', 'id': 4605662})])

        person = populi.people.by_student_id('101')

        self.assertEqual(person['id'], 4605662)
        self.assertEqual(session.calls[0]['json'], {'student_id': '101'})

    def test_unknown_student_is_none_not_an_exception(self):
        populi, _ = make([FakeResponse(404, error_body(code=404, message='not found'))])

        self.assertIsNone(populi.people.by_student_id('nope'))

    def test_a_list_answer_raises_rather_than_picking_a_row(self):
        """Picking [0] from an unexpected list hands back an arbitrary stranger."""
        populi, _ = make([FakeResponse(200, list_body([{'id': 1}, {'id': 2}], results=2))])

        with self.assertRaises(PopuliApiError):
            populi.people.by_student_id('101')

    def test_payment_link_returns_the_url(self):
        populi, _ = make(
            [FakeResponse(200, {'object': 'x', 'person_id': 1, 'url': 'https://pay'})]
        )

        self.assertEqual(populi.people.online_payment_link(1), 'https://pay')


class Leads(unittest.TestCase):
    def test_current_prefers_the_active_lead(self):
        populi, _ = make(
            [FakeResponse(200, list_body(
                [
                    {'id': 1, 'status': 'stale', 'active': False, 'most_recent': True},
                    {'id': 2, 'status': 'accepted', 'active': True, 'most_recent': False},
                ],
                results=2,
            ))]
        )

        self.assertEqual(populi.leads.current(4605662)['id'], 2)

    def test_current_status_is_none_when_there_is_no_lead(self):
        """No lead means a current student, which callers branch on."""
        populi, _ = make([FakeResponse(200, list_body([], results=0))])

        self.assertIsNone(populi.leads.current_status(4605662))

    def test_set_status_updates_the_resolved_lead(self):
        populi, session = make(
            [
                FakeResponse(200, list_body(
                    [{'id': 15249937, 'status': 'accepted', 'active': True}], results=1
                )),
                FakeResponse(200, {}),
            ]
        )

        self.assertTrue(populi.leads.set_status(4605662, LeadStatus.CONFIRMED))

        write = session.calls[1]
        self.assertEqual(write['method'], 'PUT')
        self.assertTrue(write['url'].endswith('people/4605662/leads/15249937'))
        self.assertEqual(write['json'], {'status': 'confirmed'})

    def test_a_legacy_uppercase_status_is_rejected_before_sending(self):
        """The legacy API took "CONFIRMED"; API2 takes "confirmed".

        Every ported call site is one careless copy away from the old
        vocabulary, and a rejected status change is the kind of failure this
        application swallows and logs rather than surfacing — so it is caught
        here instead of at Populi.
        """
        populi, session = make([])

        with self.assertRaises(PopuliConfigurationError):
            populi.leads.set_status(4605662, 'CONFIRMED')

        self.assertEqual(session.calls, [])

    def test_set_status_without_a_lead_is_a_no_op(self):
        populi, session = make([FakeResponse(200, list_body([], results=0))])

        self.assertFalse(populi.leads.set_status(4605662, LeadStatus.CONFIRMED))
        self.assertEqual(len(session.calls), 1)


class Notes(unittest.TestCase):
    def test_create_sends_the_parameter_populi_actually_requires(self):
        """The write parameter is `note`; the read field is `content`.

        They are not the same word and nothing documents the difference.
        Sending `content` is answered with "Missing required parameter: note",
        which is how every Background Check note silently failed — while this
        test, asserting `content`, passed. It now asserts Populi's contract
        rather than the client's intent.
        """
        populi, session = make([FakeResponse(200, {'object': 'note', 'id': 1})])

        populi.notes.create(4605662, 'hello')

        self.assertEqual(session.calls[0]['method'], 'POST')
        self.assertTrue(session.calls[0]['url'].endswith('people/4605662/notes'))
        self.assertEqual(session.calls[0]['json'], {'note': 'hello'})


class CommunicationPlans(unittest.TestCase):
    def test_delete_uses_person_then_instance_order(self):
        """The legacy call took these the other way round."""
        populi, session = make([FakeResponse(200, {})])

        populi.communication_plans.delete(4605662, 998877)

        self.assertTrue(
            session.calls[0]['url'].endswith('people/4605662/communicationplans/998877')
        )

    def test_deleting_an_absent_plan_is_not_an_error(self):
        populi, _ = make([FakeResponse(404, error_body(code=404, message='gone'))])

        self.assertFalse(populi.communication_plans.delete(4605662, 998877))


if __name__ == '__main__':
    unittest.main()
