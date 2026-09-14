"""Person custom info data.

Three things here were established by experiment against the live instance,
because the documentation answers none of them and each one silently destroys
data when guessed wrong.

**1. Writes are SCOPED.** A field belongs to a scope — ``person``,
``admissions``, ``student``, ``campuslife``, ``financial``, ``financialaid``, or
a term — and the route carries it: ``/people/{id}/custominfodata/{scope}``, with
the person scope being the bare ``/people/{id}/custominfodata``. Reading the
wrong scope does not error, it returns **no rows** — and code that treats
absence as "not set" then writes over what it failed to see. Ten of the twelve
fields this application uses are ``admissions``; one is ``campuslife``.

**2. A checkbox write REPLACES the whole selection.** Measured on field 900010
with three options selected: POSTing a single option id left **one** row, not
four. POSTing the full array set exactly that array. So "tick one more box" is
read-the-current-set, append, and POST the whole array — never POST the one
option.

**3. Row count cannot tell you whether a field is a checkbox.** A checkbox
holding exactly one selection has one row, looks single-valued, and a scalar
write to it destroys that selection — measured. ``input_type`` from the field
definition is the authoritative answer and is what this module uses.

On read, a multi-select is one row per selected option, each row's ``value`` a
scalar string holding the option **id** (the label lives in ``option_value`` and
staff rename those freely). Writes address the data **row** id, never the field
id.
"""

import logging

from ..errors import PopuliApiError, PopuliNotFoundError

logger = logging.getLogger(__name__)

PERSON_SCOPE = 'person'

# Input types that hold several values at once. Everything else replaces.
MULTI_VALUE_INPUT_TYPES = frozenset({'checkbox'})


def data_path(person_id, scope, row_id=None):
    """Route for a person's custom info data in one scope.

    The person scope is the bare path — Populi nests person-scoped values
    directly under ``/people/{id}/custominfodata`` — while every other scope
    appends its name with underscores removed (``campus_life`` → ``campuslife``).
    """
    url_scope = '' if not scope or scope == PERSON_SCOPE else scope.replace('_', '')
    path = 'people/%s/custominfodata' % person_id
    if url_scope:
        path += '/' + url_scope
    if row_id is not None:
        path += '/%s' % row_id
    return path


def term_data_path(person_id, term_id, row_id=None):
    """Route for a person's TERM-scoped custom info data.

    Keyed on the academic term, not on a field. A sibling client had this as
    ``custominfodata/student/{fieldId}`` — the student scope, with a field id in
    the slot the route reserves for a term — so it asked about the wrong scope
    entirely and could never return the caller's term-scoped rows.
    """
    path = 'people/%s/custominfodata/term/%s' % (person_id, term_id)
    if row_id is not None:
        path += '/%s' % row_id
    return path


def field_definition_path(scope):
    """Route for a scope's field DEFINITIONS.

    Deliberately not ``data_path``'s transform: the definition routes have no
    person special case — person-scoped fields live at
    ``/personcustominfofields`` — so sharing the helper would send an empty
    prefix and request ``/custominfofields``, which is a different thing.
    """
    return '%scustominfofields' % (scope or PERSON_SCOPE).replace('_', '').lower()


class FieldDefinitions:
    """Field definitions per scope, fetched once and cached.

    Cached because the answer this exists to give — is this field a checkbox —
    changes only when someone edits the field in Populi, while the question is
    asked on every write. One cached read per scope against a 50/minute budget
    is the difference between a webhook costing three requests and fifteen.
    """

    def __init__(self, client):
        self._client = client
        self._by_scope = {}

    def for_scope(self, scope):
        if scope not in self._by_scope:
            rows = self._client.list_all(field_definition_path(scope))
            self._by_scope[scope] = {str(r['id']): r for r in rows}
        return self._by_scope[scope]

    def get(self, field_id, scope):
        return self.for_scope(scope).get(str(field_id))

    def is_multi_value(self, field_id, scope):
        """Whether this field holds several values at once.

        Raises when the field is unknown in that scope rather than assuming
        single-valued: guessing wrong here silently wipes a selection, and a
        field id in the wrong scope is a real configuration error worth
        surfacing.
        """
        definition = self.get(field_id, scope)
        if definition is None:
            raise PopuliApiError(
                'custom info field %s does not exist in the %s scope; check '
                'the field id and its scope' % (field_id, scope),
                status_code=404,
                endpoint=field_definition_path(scope),
                populi_type='object_not_found',
            )
        return definition.get('input_type') in MULTI_VALUE_INPUT_TYPES

    def clear(self):
        self._by_scope.clear()


class CustomFields:
    """Read and write a person's custom info data.

    Every method takes ``scope``. It has no default on purpose: defaulting to
    the person scope would make the common case — an ``admissions`` field —
    silently read empty and then overwrite.
    """

    def __init__(self, client, definitions=None):
        self._client = client
        self.definitions = definitions or FieldDefinitions(client)

    # -- reads -----------------------------------------------------------

    def list(self, person_id, scope):
        """Every custom info data row a person holds in one scope."""
        return self._client.list_all(data_path(person_id, scope))

    def rows_for_field(self, person_id, field_id, scope):
        """Every row a person holds for one field.

        Plural by necessity: a checkbox has one row per selected option, so a
        singular accessor would silently see only the first.
        """
        field_id = str(field_id)
        return [
            row for row in self.list(person_id, scope)
            if str(row.get('custom_info_field_id')) == field_id
        ]

    def get_values(self, person_id, field_id, scope):
        """Every value held for a field, as strings. Empty when unset."""
        return [row.get('value') for row in self.rows_for_field(person_id, field_id, scope)]

    def get_value(self, person_id, field_id, scope):
        """The single value held for a field, or None."""
        values = self.get_values(person_id, field_id, scope)
        if not values:
            return None
        if len(values) > 1:
            logger.warning(
                'populi person %s holds %d values for field %s (%s); returning '
                'the first. Use get_values() for checkbox fields.',
                person_id, len(values), field_id, scope,
            )
        return values[0]

    # -- writes ----------------------------------------------------------

    def set_value(self, person_id, field_id, scope, value, verify=True):
        """Set a single-valued field, replacing whatever was there."""
        return self._write(person_id, field_id, scope, [value], verify=verify)

    def set_options(self, person_id, field_id, scope, option_ids, verify=True):
        """Set a field to exactly these options, discarding any others.

        Destructive by design and named for it. Callers that mean "tick one more
        box" use ``add_option``, so the intent is visible at the call site
        rather than depending on what the caller happened to read first.
        """
        return self._write(person_id, field_id, scope, list(option_ids), verify=verify)

    def add_option(self, person_id, field_id, scope, option_id, verify=True):
        """Tick one more box, keeping every option already selected.

        This is the safe default and what the application's automations mean.
        A checkbox write replaces the whole selection, so the current set is
        read first and the new option appended — posting the option on its own
        would leave it as the ONLY selection.
        """
        current = self.get_values(person_id, field_id, scope)

        if str(option_id) in {str(v) for v in current}:
            # Already ticked. Doing nothing keeps a webhook delivered twice from
            # rewriting the whole set for no change.
            logger.debug(
                'populi person %s already has option %s on field %s (%s)',
                person_id, option_id, field_id, scope,
            )
            return False

        return self._write(
            person_id, field_id, scope, current + [option_id], verify=verify
        )

    def remove_option(self, person_id, field_id, scope, option_id, verify=True):
        """Untick one box, keeping the others."""
        current = self.get_values(person_id, field_id, scope)
        remaining = [v for v in current if str(v) != str(option_id)]

        if len(remaining) == len(current):
            return False

        return self._write(person_id, field_id, scope, remaining, verify=verify)

    def definitions_for_scope(self, scope):
        """Every custom info field defined in one scope.

        Straight from the cache the write path already fills, so asking twice
        costs one request. Use it to discover ids rather than hardcoding them —
        they are instance-specific.
        """
        return list(self.definitions.for_scope(scope).values())

    def definition(self, field_id, scope, include_options=False):
        """One field's definition, optionally with its answer options.

        Options come **only** from the show route and **only** when asked for.
        Every index route omits them, so a missing ``options`` key means the
        expand was not honoured — never that the field has none. That
        distinction is asserted here rather than left to the caller.

        Each option carries a ``retired`` flag, and retired is not unused: a
        retired option stays on every record already holding it. Never infer
        retirement from usage — read the flag.
        """
        parameters = {'expand': ['options']} if include_options else None
        # No trailing slash. This was the only call in the client carrying one,
        # and it is the form that has NOT been driven against a live instance;
        # the unslashed form has, repeatedly. Two spellings of one route is a
        # coin flip nobody should have to call at runtime.
        field = self._client.get(
            '%s/%s' % (field_definition_path(scope), field_id), parameters
        )

        if include_options and field.get('options') is None:
            raise PopuliApiError(
                'field %s came back without the requested options expansion, so '
                'the option list is unknown rather than empty' % field_id,
                status_code=200,
                endpoint=field_definition_path(scope),
                populi_type='expand_dropped',
            )

        return field

    # -- term-scoped data ---------------------------------------------------

    def term_values(self, person_id, term_id, field_id=None):
        """A person's term-scoped custom info data, optionally for one field."""
        rows = self._client.list_all(term_data_path(person_id, term_id))
        if field_id is None:
            return rows
        return [r for r in rows if str(r.get('custom_info_field_id')) == str(field_id)]

    def set_term_value(self, person_id, term_id, field_id, value):
        """Create a term-scoped value."""
        return self._client.post(
            term_data_path(person_id, term_id),
            {'custom_info_field_id': field_id, 'value': value},
        )

    def update_term_value(self, person_id, term_id, row_id, value):
        """Update a term-scoped value by its DATA ROW id, not the field id."""
        return self._client.put(
            term_data_path(person_id, term_id, row_id), {'value': value}
        )

    def delete_term_value(self, person_id, term_id, row_id):
        """Delete a term-scoped row.

        ``term_id`` is not optional and is easy to omit: the route is
        ``custominfodata/term/{academicterm}/{custominfodata}``, and a sibling
        client once built it as ``custominfodata/student/{dataId}`` — a
        different scope, with a data id in the slot that names the term.
        """
        try:
            self._client.delete(term_data_path(person_id, term_id, row_id))
        except PopuliNotFoundError:
            return False
        return True

    def delete(self, person_id, field_id, scope):
        """Remove every value a person holds for a field.

        Deletes each row by its own id — the API2 delete addresses the row, not
        the field. False when there was nothing to delete, which is normal:
        these run from webhooks that can arrive more than once.
        """
        rows = self.rows_for_field(person_id, field_id, scope)
        if not rows:
            logger.debug(
                'populi person %s has no values for field %s (%s); nothing to delete',
                person_id, field_id, scope,
            )
            return False

        for row in rows:
            self._delete_row(person_id, scope, row['id'])

        return True

    # -- internals -------------------------------------------------------

    def _write(self, person_id, field_id, scope, values, verify=True):
        """Make the field hold exactly ``values``.

        A multi-value field takes the whole array in one POST — Populi expands
        it into rows and discards anything not listed. A single-valued field
        takes the scalar. An empty set is a delete, because POSTing an empty
        array is not a documented way to clear a field and guessing at it is how
        a value survives a clear that reported success.
        """
        if not values:
            return self.delete(person_id, field_id, scope)

        multi = self.definitions.is_multi_value(field_id, scope)

        if multi:
            payload = [str(v) for v in values]
        else:
            if len(values) > 1:
                raise PopuliApiError(
                    'field %s (%s) is %r and holds one value, but %d were given'
                    % (field_id, scope,
                       (self.definitions.get(field_id, scope) or {}).get('input_type'),
                       len(values)),
                    status_code=400,
                    endpoint=data_path(person_id, scope),
                    populi_type='invalid_parameter',
                )
            payload = values[0]

        self._client.post(
            data_path(person_id, scope),
            {'custom_info_field_id': field_id, 'value': payload},
        )

        if verify:
            self._assert_values(person_id, field_id, scope, {str(v) for v in values})

        return True

    def _delete_row(self, person_id, scope, row_id):
        try:
            self._client.delete(data_path(person_id, scope, row_id))
        except PopuliNotFoundError:
            # Removed between the read and the delete; the end state is the one
            # that was asked for.
            logger.debug(
                'populi custominfodata row %s already gone for person %s',
                row_id, person_id,
            )

    def _assert_values(self, person_id, field_id, scope, expected):
        """Confirm the write landed.

        Populi can accept a write and not apply it. This is the opposite of the
        discipline used for tags, whose index lags a write by minutes — custom
        info data reads back immediately, measured, so the assertion is
        meaningful here and would be misleading there.

        **Compared against the option LABEL as well as the id**, because an
        option field accepts either on the way in and always reports the id on
        the way out. Writing "In Progress" to a radio stores option 458178 and
        reads back as '458178' — a successful write that an id-only comparison
        calls a failure. Measured: that turned every application status update
        into a logged error and a notification email while the value was
        correctly set. An assertion has to be made on something the API actually
        moves, or it reports success as failure.
        """
        rows = self.rows_for_field(person_id, field_id, scope)
        actual = {str(row.get('value')) for row in rows}
        actual_labels = {str(row.get('option_value')) for row in rows if row.get('option_value')}

        if actual == expected or actual_labels == expected:
            return

        raise PopuliApiError(
            'field %s (%s) on person %s reads back as %s after writing %s'
            % (field_id, scope, person_id, sorted(actual), sorted(expected)),
            status_code=200,
            endpoint=data_path(person_id, scope),
            populi_type='write_not_applied',
        )
