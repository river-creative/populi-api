"""Build Populi filter envelopes.

**Populi filters fail OPEN.** A condition it cannot read — a misspelled ``name``,
a value missing a required sub-key, a group keyed as a list instead of ``"0"`` —
is silently discarded and the request still answers **HTTP 200 with the entire
unfiltered list**. A hand-built envelope therefore has no failure mode that looks
like one: it returns plausible data about the wrong people.

This builder removes the STRUCTURAL mistakes. It cannot check a condition name
against a route, so the rule that matters still stands:

    Verify a new filter against the live API and confirm the result set actually
    NARROWED. A query returning more than expected is the signature of a dropped
    condition.

The reliable way to discover a shape is Populi's own UI: build the filter on an
index page, save it as a preset, edit the preset, and use **"Show JSON for API"**.

Mirrors ``PopuliFilter`` in the .NET client, including that an empty filter
raises rather than being sent — ``{"filter":{}}`` parses perfectly and matches
everyone.
"""

import hashlib
import json

from .errors import PopuliConfigurationError

ALL = 'ALL'
ANY = 'ANY'


class PopuliFilter:
    """A filter envelope, assembled group by group.

    Groups are AND-ed with each other; ``logic`` decides how the conditions
    within one group combine::

        PopuliFilter().all_of().where('first_name', {'type': 'STARTS_WITH', 'text': 'Jo'}).to_dict()
    """

    def __init__(self):
        self._groups = []

    # -- group construction ----------------------------------------------

    def all_of(self):
        """Start a group whose conditions must all match."""
        self._groups.append({'logic': ALL, 'fields': []})
        return self

    def any_of(self):
        """Start a group where any condition matching is enough."""
        self._groups.append({'logic': ANY, 'fields': []})
        return self

    def where(self, name, value, positive=True):
        """Add a condition to the current group.

        ``positive=False`` NEGATES it. Populi spells that as ``positive: "0"``,
        as a string — the published examples show a bare integer and the live
        API accepts both, so the string form is used because that is what
        Populi's own "Show JSON for API" emits.
        """
        if not self._groups:
            raise PopuliConfigurationError(
                'start a group with all_of() or any_of() before adding a condition'
            )

        self._groups[-1]['fields'].append({
            'name': name,
            'value': value,
            'positive': '1' if positive else '0',
        })
        return self

    def where_custom_field(self, field_id, positive=True):
        """Match people who HAVE an answer for a custom field.

        Note the reversal, which catches people out: Populi spells blankness as
        ``choice: "BLANK"``, so "has an answer" is that condition **negated**.
        Reading it the obvious way round inverts the population — you select
        exactly the people you meant to exclude.

        ``custom_info_field_id`` travels as a **string**. Sent as a number the
        condition is dropped and the filter silently widens.
        """
        return self.where(
            'custom_field',
            {'custom_info_field_id': str(field_id), 'choice': 'BLANK'},
            positive=not positive,
        )

    def where_tag(self, tag_id, positive=True):
        return self.where('tag', {'tag_id': str(tag_id)}, positive=positive)

    # -- output ------------------------------------------------------------

    def to_dict(self):
        """The envelope, ready to go in a request's ``filter`` key.

        Raises on an empty filter or an empty group. Populi ignores both, and
        an ignored filter matches everyone — which is the difference between a
        report about forty people and a report about forty thousand.
        """
        if not self._groups:
            raise PopuliConfigurationError(
                'this filter has no groups; Populi would ignore it and match everyone'
            )

        for index, group in enumerate(self._groups):
            if not group['fields']:
                raise PopuliConfigurationError(
                    'filter group %d has no conditions; Populi would ignore it '
                    'and match everyone' % index
                )

        return {str(i): group for i, group in enumerate(self._groups)}

    def to_json(self):
        return json.dumps(self.to_dict())

    def fingerprint(self):
        """A stable hash of the PARSED filter.

        Hashes the document rather than its text, so a filter that has been
        pretty-printed for display keeps its identity — a raw-text hash forgets
        a verified match count over a stray newline.
        """
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def __repr__(self):
        return '<PopuliFilter %d group(s)>' % len(self._groups)


def is_well_formed(filter_json):
    """Whether a filter STRING is structurally readable by Populi.

    Blank is valid and means *no filter* — that is how an operator clears a
    stored override, so it is not an error here.

    This only asks whether the text parses into the right shape. It cannot
    reach the semantic mistakes: a misspelled condition name is structurally
    perfect and still discarded.
    """
    if filter_json is None or not str(filter_json).strip():
        return True

    try:
        parsed = json.loads(filter_json)
    except (TypeError, ValueError):
        return False

    if not isinstance(parsed, dict) or not parsed:
        return False

    for group in parsed.values():
        if not isinstance(group, dict):
            return False
        if group.get('logic') not in (ALL, ANY):
            return False
        if not isinstance(group.get('fields'), list) or not group['fields']:
            return False

    return True
