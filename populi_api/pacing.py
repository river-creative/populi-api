"""Request pacing for a shared Populi API key.

Split the same way as the .NET ``Populi.Client``: a **schedule** says which
budget is in force right now, and a **pacer** converts a budget into a minimum
interval and enforces it. They are separate because the first is a statement
about Populi and the second is a policy choice by the caller.

Populi's published budget is **50 requests/minute between 03:00 and 19:00
Pacific, and 100/minute outside that**, per API key across every process using
it, plus additional per-IP and per-school limits. Going over answers HTTP 429,
whose remedy is a pause of just over a minute — expensive enough that pacing is
far cheaper than reacting.

Three things this gets right that are easy to get wrong:

* **A concurrency cap is not a rate limit.** Five concurrent requests with a
  200ms delay is ~1,500/minute — thirty times the daytime budget. What paces is
  a minimum interval between request *starts*, with the next slot claimed under
  a lock so concurrent callers queue instead of all reading the same clock and
  firing together.
* **The budget is not one number**, so a fixed interval is wrong half the day.
  It is re-read per request, so a long run crossing 19:00 Pacific widens by
  itself rather than staying throttled for hours.
* **Never pace at exactly the budget.** 1200ms is precisely 60000/50, which
  reads as correct and provisions one job to consume the whole key. The budget
  belongs to the KEY, shared with every other caller including interactive
  lookups someone is waiting on, so a caller claims a *share*.

Concretely here: one `vsp` application fires nine tag writes, and a single
webhook plausibly costs a dozen calls or more.
"""

import threading
import time
from datetime import datetime, time as time_of_day
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import PopuliConfigurationError

# Populi states the boundary in Pacific time. This project's own TIME_ZONE is
# America/New_York, and reading the boundary there would switch budgets three
# hours early — spending the daytime allowance at the night rate.
BUDGET_TIMEZONE = 'America/Los_Angeles'


class RateSchedule:
    """Which request budget is in force at a given moment.

    The boundary is deliberately not treated as exact. Populi's documentation
    says "PST" literally rather than "Pacific Time", so during daylight saving
    it is genuinely unclear whether the switch happens at 03:00 PDT or 03:00
    PST — an hour apart. This resolves the school's Pacific wall clock and
    claims no more precision than that, which is a further reason for a caller
    to spend a fraction of the budget rather than all of it.
    """

    def __init__(
        self,
        daytime_requests_per_minute=50,
        overnight_requests_per_minute=100,
        weekend_requests_per_minute=None,
        daytime_start=time_of_day(3, 0),
        daytime_end=time_of_day(19, 0),
        timezone_name=BUDGET_TIMEZONE,
    ):
        try:
            self.timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            # Raised rather than falling back to UTC. Silently pacing an
            # eight-hour window three hours off is the confident-wrong failure
            # that costs more than an outage: nothing reports it, and the 429s
            # read as Populi being flaky.
            raise PopuliConfigurationError(
                'time zone %r is unavailable, so the Populi rate budget cannot '
                'be determined; install the system tz database or the tzdata '
                'package' % timezone_name
            ) from exc

        self.daytime_requests_per_minute = daytime_requests_per_minute
        self.overnight_requests_per_minute = overnight_requests_per_minute
        # None by default, and that is a factual statement rather than a
        # conservative one: Populi's reference documents the time-of-day split
        # and says nothing about the day of the week. Settable because a wider
        # weekend allowance is plausible and worth exploiting — but a rate limit
        # is the wrong place for a plausible number. Guessing high does not fail
        # loudly; it produces 429s and a backoff slower than the conservative
        # setting would have been. Measure it, then set it.
        self.weekend_requests_per_minute = weekend_requests_per_minute
        self.daytime_start = daytime_start
        self.daytime_end = daytime_end

    def requests_per_minute_at(self, instant=None):
        local = (instant or datetime.now(self.timezone)).astimezone(self.timezone)

        if self.weekend_requests_per_minute is not None and local.weekday() >= 5:
            return self.weekend_requests_per_minute

        # Half-open on purpose: 19:00:00 exactly belongs to the overnight
        # window, so a boundary instant is never counted in both.
        if self.daytime_start <= local.time() < self.daytime_end:
            return self.daytime_requests_per_minute

        return self.overnight_requests_per_minute


class Pacer:
    """Enforces a minimum interval between request starts.

    ``utilisation`` has no default deliberately: a caller must state what share
    of the shared key budget it is claiming rather than taking all of it by
    omission. 0.8 is a reasonable claim for a background job. Interactive
    callers are better left unpaced than given a small share — the point is to
    pace the caller that needs slowing, not the process.
    """

    def __init__(
        self,
        utilisation,
        schedule=None,
        clock=time.monotonic,
        sleep=time.sleep,
        now=None,
    ):
        if not 0 < utilisation <= 1:
            raise PopuliConfigurationError(
                'utilisation must be greater than 0 and at most 1, got %r'
                % (utilisation,)
            )

        self.utilisation = utilisation
        self.schedule = schedule or RateSchedule()
        self._clock = clock
        self._sleep = sleep
        self._now = now

        self._lock = threading.Lock()
        self._next_slot = None

    def requests_per_minute(self):
        """The budget in force right now, before this caller's share."""
        instant = self._now() if self._now else None
        return self.schedule.requests_per_minute_at(instant)

    def interval_seconds(self):
        """Minimum seconds between request starts at the current budget."""
        return 60.0 / (self.requests_per_minute() * self.utilisation)

    def acquire(self):
        """Block until this caller may start its request.

        The slot is claimed while holding the lock and the sleep happens outside
        it, so concurrent callers queue for distinct slots rather than all
        waking at the same instant.
        """
        with self._lock:
            now = self._clock()
            interval = self.interval_seconds()

            if self._next_slot is None or self._next_slot <= now:
                # Idle long enough that the window has cleared: go now, and
                # reserve the following slot from this moment.
                self._next_slot = now + interval
                return 0.0

            wait = self._next_slot - now
            self._next_slot += interval

        self._sleep(wait)
        return wait


class NullPacer:
    """Pacing disabled — for interactive callers and for tests.

    A named type rather than ``None`` so call sites never branch on whether a
    pacer exists.
    """

    def requests_per_minute(self):
        return None

    def interval_seconds(self):
        return 0.0

    def acquire(self):
        return 0.0
