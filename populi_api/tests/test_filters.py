"""Filter construction.

Populi discards a filter condition it cannot read and answers 200 with the whole
unfiltered list, so the failures worth testing are the ones that produce a
STRUCTURALLY VALID filter meaning something other than intended — and the empty
cases, which match everyone.
"""

import unittest

from ..errors import PopuliConfigurationError
from ..filters import PopuliFilter, is_well_formed


class Building(unittest.TestCase):
    def test_groups_are_keyed_by_position(self):
        """Keyed "0", "1", … — an array here is silently ignored."""
        built = (PopuliFilter()
                 .all_of().where('first_name', {'type': 'EQUALS', 'text': 'Jo'})
                 .any_of().where('last_name', {'type': 'EQUALS', 'text': 'Smith'}))

        envelope = built.to_dict()
        self.assertEqual(sorted(envelope), ['0', '1'])
        self.assertEqual(envelope['0']['logic'], 'ALL')
        self.assertEqual(envelope['1']['logic'], 'ANY')

    def test_an_empty_filter_raises_rather_than_matching_everyone(self):
        with self.assertRaises(PopuliConfigurationError):
            PopuliFilter().to_dict()

    def test_an_empty_group_raises(self):
        """{"0": {"logic":"ALL","fields":[]}} is ignored, which matches everyone."""
        with self.assertRaises(PopuliConfigurationError):
            PopuliFilter().all_of().to_dict()

    def test_a_condition_without_a_group_raises(self):
        with self.assertRaises(PopuliConfigurationError):
            PopuliFilter().where('first_name', {'type': 'EQUALS', 'text': 'Jo'})

    def test_has_an_answer_is_BLANK_negated(self):
        """The reversal that inverts a population if read the obvious way round.

        Populi spells blankness as choice BLANK, so "has an answer" is that
        condition negated — select it positively and you get exactly the people
        you meant to exclude.
        """
        envelope = PopuliFilter().all_of().where_custom_field(212516).to_dict()
        condition = envelope['0']['fields'][0]

        self.assertEqual(condition['value']['choice'], 'BLANK')
        self.assertEqual(condition['positive'], '0')

    def test_custom_field_id_travels_as_a_string(self):
        """Sent as a number the condition is dropped and the filter widens."""
        envelope = PopuliFilter().all_of().where_custom_field(212516).to_dict()
        self.assertIsInstance(
            envelope['0']['fields'][0]['value']['custom_info_field_id'], str
        )

    def test_fingerprint_ignores_formatting(self):
        """Hashes the parsed document, so pretty-printing does not change identity."""
        a = PopuliFilter().all_of().where('x', {'type': 'EQUALS', 'text': '1'})
        b = PopuliFilter().all_of().where('x', {'type': 'EQUALS', 'text': '1'})
        self.assertEqual(a.fingerprint(), b.fingerprint())


class WellFormed(unittest.TestCase):
    def test_blank_is_valid_and_means_no_filter(self):
        """How an operator clears a stored override — not an error."""
        for blank in (None, '', '   '):
            self.assertTrue(is_well_formed(blank))

    def test_an_empty_object_is_not_well_formed(self):
        """{} parses perfectly and matches everyone, which is the trap."""
        self.assertFalse(is_well_formed('{}'))

    def test_a_group_with_no_conditions_is_not_well_formed(self):
        self.assertFalse(is_well_formed('{"0": {"logic": "ALL", "fields": []}}'))

    def test_unparseable_text_is_not_well_formed(self):
        self.assertFalse(is_well_formed('{not json'))

    def test_a_real_filter_is_well_formed(self):
        built = PopuliFilter().all_of().where('x', {'type': 'EQUALS', 'text': '1'})
        self.assertTrue(is_well_formed(built.to_json()))


if __name__ == '__main__':
    unittest.main()
