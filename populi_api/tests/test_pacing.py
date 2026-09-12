"""Rate budget and pacing.

The budget boundary is the part worth testing: it is invisible when wrong — a
schedule three hours off produces 429s that read as Populi being flaky, not as
a configuration error.
"""

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from ..errors import PopuliConfigurationError
from ..pacing import Pacer, RateSchedule

PACIFIC = ZoneInfo('America/Los_Angeles')


def pacific(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=PACIFIC)


class Schedule(unittest.TestCase):
    def setUp(self):
        self.schedule = RateSchedule()

    def test_daytime_window_is_the_lower_budget(self):
        # A Wednesday.
        self.assertEqual(
            self.schedule.requests_per_minute_at(pacific(2026, 9, 9, 10)), 50
        )

    def test_overnight_window_is_the_higher_budget(self):
        self.assertEqual(
            self.schedule.requests_per_minute_at(pacific(2026, 9, 9, 22)), 100
        )

    def test_boundaries_are_half_open(self):
        """03:00 is daytime; 19:00 exactly belongs to the overnight window.

        Half-open so a boundary instant is never counted in both.
        """
        self.assertEqual(
            self.schedule.requests_per_minute_at(pacific(2026, 9, 9, 3)), 50
        )
        self.assertEqual(
            self.schedule.requests_per_minute_at(pacific(2026, 9, 9, 19)), 100
        )

    def test_the_boundary_is_read_in_pacific_not_the_project_timezone(self):
        """22:00 Eastern is 19:00 Pacific — the overnight budget.

        Reading this in America/New_York, which is the project's TIME_ZONE,
        would call it daytime and pace at half the available rate.
        """
        eastern = datetime(2026, 9, 9, 22, tzinfo=ZoneInfo('America/New_York'))
        self.assertEqual(self.schedule.requests_per_minute_at(eastern), 100)

    def test_weekend_is_not_special_unless_measured(self):
        """Populi documents the time-of-day split and nothing about weekdays.

        Left unset, a Saturday follows the ordinary rule — the only behaviour
        the documentation supports.
        """
        saturday = pacific(2026, 9, 12, 10)
        self.assertEqual(self.schedule.requests_per_minute_at(saturday), 50)

        measured = RateSchedule(weekend_requests_per_minute=200)
        self.assertEqual(measured.requests_per_minute_at(saturday), 200)

    def test_an_unavailable_timezone_raises_rather_than_guessing(self):
        with self.assertRaises(PopuliConfigurationError):
            RateSchedule(timezone_name='Not/AZone')


class Pacing(unittest.TestCase):
    def test_utilisation_must_be_a_share(self):
        for bad in (0, -1, 1.5):
            with self.subTest(utilisation=bad):
                with self.assertRaises(PopuliConfigurationError):
                    Pacer(utilisation=bad)

    def test_interval_is_a_share_of_the_budget_not_the_whole_of_it(self):
        """1200ms is exactly 60000/50 and would claim the entire key."""
        pacer = Pacer(utilisation=0.8, now=lambda: pacific(2026, 9, 9, 10))
        self.assertAlmostEqual(pacer.interval_seconds(), 1.5)

    def test_interval_widens_overnight(self):
        pacer = Pacer(utilisation=0.8, now=lambda: pacific(2026, 9, 9, 22))
        self.assertAlmostEqual(pacer.interval_seconds(), 0.75)

    def test_first_request_does_not_wait(self):
        clock = iter([0.0])
        pacer = Pacer(
            utilisation=0.8,
            clock=lambda: next(clock),
            sleep=lambda _: None,
            now=lambda: pacific(2026, 9, 9, 10),
        )
        self.assertEqual(pacer.acquire(), 0.0)

    def test_a_following_request_waits_for_its_slot(self):
        times = iter([0.0, 0.0])
        slept = []
        pacer = Pacer(
            utilisation=0.8,
            clock=lambda: next(times),
            sleep=slept.append,
            now=lambda: pacific(2026, 9, 9, 10),
        )

        pacer.acquire()
        waited = pacer.acquire()

        self.assertAlmostEqual(waited, 1.5)
        self.assertEqual(len(slept), 1)

    def test_slots_are_distinct_so_concurrent_callers_queue(self):
        """Each caller claims its own slot rather than all reading one clock."""
        times = iter([0.0, 0.0, 0.0])
        pacer = Pacer(
            utilisation=0.8,
            clock=lambda: next(times),
            sleep=lambda _: None,
            now=lambda: pacific(2026, 9, 9, 10),
        )

        pacer.acquire()
        first = pacer.acquire()
        second = pacer.acquire()

        self.assertAlmostEqual(first, 1.5)
        self.assertAlmostEqual(second, 3.0)


if __name__ == '__main__':
    unittest.main()
