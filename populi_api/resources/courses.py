"""Course offerings, assignments, rosters and assignment grades.

The grade routes carry three traps that cost real debugging, all measured rather
than documented. They are the reason this module exists as something other than
thin wrappers.

**1. The unit changes between write and read.** ``set_grade`` takes POINTS
EARNED and the response reports a PERCENT. Write 1 to a 1-point assignment and
Populi answers ``grade: 100``. A verifying read that compares against the number
it sent therefore fails on *every success*, reporting the write as broken while
the transcript is correct.

**2. Excusing is a GRADE, not a flag.** Send the grade ``"E"``. The route also
accepts an ``excused`` parameter, returns 200, and **ignores it** — the most
expensive shape available, because nothing indicates the request did nothing.

**3. There is no bulk route.** One student, one assignment, one request. A
term's grading is thousands of calls against a 50/minute key, so the pacer is
the only lever — see :class:`populi_api.pacing.Pacer`.
"""

import logging

from ..errors import PopuliApiError

logger = logging.getLogger(__name__)

# Populi's spelling for "this student is excused from this assignment".
EXCUSED = 'E'


class Courses:
    """Course offerings, their assignments and rosters, and grades."""

    def __init__(self, client):
        self._client = client

    # -- offerings and rosters --------------------------------------------

    def offerings(self, academic_term_id=None, expand=None):
        parameters = {}
        if academic_term_id:
            parameters['academic_term_id'] = academic_term_id
        if expand:
            parameters['expand'] = list(expand)
        return self._client.list_all('courseofferings', parameters or None)

    def offering(self, course_offering_id, expand=None):
        parameters = {'expand': list(expand)} if expand else None
        return self._client.get('courseofferings/%s' % course_offering_id, parameters)

    def assignments(self, course_offering_id):
        return self._client.list_all(
            'courseofferings/%s/assignments' % course_offering_id
        )

    def enrollments(self, course_offering_id, expand=None):
        """The roster for an offering.

        **A row's ``student_id`` is a PERSON id, not the visible student id.**
        Measured on a live instance: an enrollment reporting
        ``student_id: 24564256`` resolves at ``GET /people/24564256``, and
        ``people.by_student_id(24564256)`` finds nobody — the two numbering
        schemes are unrelated and the name only matches one of them.

        The rows carry no ``person_id`` key at all, so ``student_id`` is the
        only identifier available and the mistake is easy to make in both
        directions. It is the right value to pass straight to
        :meth:`set_grade`, :meth:`grade` and :meth:`excuse`, all of which take a
        person id. It is the wrong value to hand to anything resolving a
        *visible* student id, which will silently find nothing rather than fail.
        """
        parameters = {'expand': list(expand)} if expand else None
        return self._client.list_all(
            'courseofferings/%s/students' % course_offering_id, parameters
        )

    # -- grades ------------------------------------------------------------

    def grade(self, course_offering_id, assignment_id, person_id):
        """One student's grade for one assignment.

        An ungraded student answers with an **empty object**, not a 404 — so
        ``{}`` means "no grade yet" and is not an error.
        """
        return self._client.get(
            'courseofferings/%s/assignments/%s/students/%s/grade'
            % (course_offering_id, assignment_id, person_id)
        )

    def set_grade(self, course_offering_id, assignment_id, person_id, points):
        """Grade an assignment, in POINTS EARNED.

        The response reports a PERCENT, so do not compare it against what you
        sent — ``set_grade(..., points=1)`` on a 1-point assignment answers
        ``grade: 100``, and a check for equality calls that a failed write.

        ``None`` is rejected by Populi with a 400 and is refused here instead,
        because the two things a caller might mean by it — clear the grade, or
        excuse the student — are both expressible and neither is "send null".
        """
        if points is None:
            raise PopuliApiError(
                'points cannot be None: use clear_grade() to remove a grade, or '
                'excuse() to excuse the student',
                status_code=400,
                endpoint='courseofferings/%s/assignments/%s/students/%s/grade/update'
                         % (course_offering_id, assignment_id, person_id),
                populi_type='invalid_parameter',
            )

        return self._update_grade(course_offering_id, assignment_id, person_id, points)

    def excuse(self, course_offering_id, assignment_id, person_id):
        """Excuse a student from an assignment.

        Done by sending the GRADE ``"E"``. There is an ``excused`` parameter on
        the route; it is accepted, answered 200, and ignored. Setting it instead
        of the grade leaves the student unexcused with nothing to show for the
        request.
        """
        return self._update_grade(
            course_offering_id, assignment_id, person_id, EXCUSED
        )

    def clear_grade(self, course_offering_id, assignment_id, person_id):
        """Return an assignment to ungraded, by sending an empty grade."""
        return self._update_grade(course_offering_id, assignment_id, person_id, '')

    def _update_grade(self, course_offering_id, assignment_id, person_id, grade):
        path = ('courseofferings/%s/assignments/%s/students/%s/grade/update'
                % (course_offering_id, assignment_id, person_id))
        return self._client.put(path, {'grade': grade})
