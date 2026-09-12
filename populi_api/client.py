"""HTTP transport for the Populi API2.

Plain Python by design: no Django import anywhere in this module, no settings
lookup, every dependency passed to the constructor.

Four behaviours here are not general HTTP hygiene — they exist because of how
Populi specifically fails:

1. **Every response is checked for ``{"object": "error"}`` regardless of HTTP
   status.** Populi reports errors under a 2xx, and on a list route such a body
   deserializes to an empty ``data`` array — indistinguishable from "no results"
   at the call site. One string comparison prevents a failed call being read as
   an empty one.
2. **429 pauses for just over a minute**, which is Populi's own documented
   instruction, rather than the short backoff used for 502/503/504. A backoff
   shorter than the window merely burns retries inside it. ``Retry-After`` is
   undocumented for this API; it is honoured when present, but the minute-plus
   pause is the contract rather than the fallback.
3. **Writes are not replayed when the outcome is unknown.** A
   ``POST /people/{id}/custominfodata`` that timed out may have been applied;
   replaying it creates a SECOND data row and the app then holds two values for
   one field. Reads are replayed freely, writes only when the caller states the
   operation is idempotent. A 429 is the exception in the other direction: the
   request was *refused*, so nothing was applied and replay is always safe.
4. **Paged reads verify the page echo and refuse a short read.** Both failures
   are otherwise silent — a paging parameter that never reaches Populi returns
   page 1 forever while looking like healthy paging, and a dropped page returns
   a shorter list rather than an error.
"""

import logging
import time

import requests

from .errors import (
    PopuliApiError,
    PopuliAuthError,
    PopuliConfigurationError,
    PopuliIncompleteReadError,
    PopuliNotFoundError,
    PopuliPagingError,
    PopuliRateLimitError,
)
from .pacing import NullPacer, Pacer

logger = logging.getLogger(__name__)

# Populi's documented remedy for a 429 is to pause "just over a minute" so the
# window is guaranteed to have reset.
RATE_LIMIT_PAUSE_SECONDS = 65

# Server-side failures worth retrying. Deliberately not "any 5xx": a 500 is an
# application fault that a replay reproduces, while these three are the
# gateway/overload statuses that clear on their own.
RETRYABLE_SERVER_STATUSES = frozenset({502, 503, 504})

# API2 caps a list response at 200 records however many are asked for.
MAX_PAGE_SIZE = 200

# An absolute ceiling on pages walked, so a route that reports no page at all
# cannot spin forever.
MAX_PAGES = 200


class PopuliClient:
    """A configured, paced connection to one school's Populi API2.

    ``base_url`` is the full API2 root, e.g. ``https://<school>.populiweb.com/api2/``.
    ``pacer`` defaults to none: a caller states its claim on the shared key
    budget explicitly rather than having one chosen for it.
    """

    def __init__(
        self,
        base_url,
        access_key,
        pacer=None,
        session=None,
        timeout=30,
        max_retries=3,
        sleep=time.sleep,
    ):
        if not base_url:
            raise PopuliConfigurationError('base_url is required')
        if not access_key:
            raise PopuliConfigurationError('access_key is required')

        self.base_url = base_url.rstrip('/') + '/'
        self._access_key = access_key
        self._pacer = pacer or NullPacer()
        self._timeout = timeout
        self._max_retries = max_retries
        self._sleep = sleep

        self._session = session or requests.Session()
        self._session.headers.update(
            {
                'Authorization': 'Bearer %s' % access_key,
                'Accept': 'application/json',
            }
        )

    # -- shared plumbing, for the routes that are not plain JSON ----------
    #
    # File download and the multipart photo upload cannot go through the verbs
    # below — one returns bytes, the other must let requests write the multipart
    # boundary. They are still subject to pacing and to the same error
    # detection, so those two pieces are public rather than reached for through
    # a private name.

    @property
    def session(self):
        """The underlying HTTP session, carrying the auth header."""
        return self._session

    @property
    def timeout(self):
        return self._timeout

    def pace(self):
        """Claim this caller's slot in the key's request budget."""
        return self._pacer.acquire()

    def error_for(self, response, endpoint):
        """An exception for this response, or None if it succeeded."""
        return self._error_for(response, endpoint)

    def with_pacing(self, utilisation):
        """A view of this client whose requests claim ``utilisation`` of the budget.

        Shares the session, credentials and configuration — a share to claim,
        not a second client. Mirrors ``WithPacing`` in the .NET client, and
        exists for the same reason: a bulk job needs slowing down, while an
        interactive lookup somebody is waiting on does not, and pacing the
        PROCESS taxes both to slow one.
        """
        view = PopuliClient(
            base_url=self.base_url,
            access_key=self._access_key,
            pacer=Pacer(utilisation=utilisation),
            session=self._session,
            timeout=self._timeout,
            max_retries=self._max_retries,
            sleep=self._sleep,
        )
        return view

    # -- verbs -----------------------------------------------------------

    def get(self, path, parameters=None):
        """A single GET. Always replayable — reads have no side effects."""
        return self._execute('GET', path, payload=parameters, retry_safe=True)

    def post(self, path, payload=None, retry_safe=False):
        """A POST. Not replayed on an unknown outcome unless the caller opts in.

        ``retry_safe=True`` is for writes whose duplicate is provably harmless —
        a tag add, which Populi answers with "Tag already added".
        """
        return self._execute('POST', path, payload=payload, retry_safe=retry_safe)

    def put(self, path, payload=None, retry_safe=False):
        return self._execute('PUT', path, payload=payload, retry_safe=retry_safe)

    def delete(self, path, payload=None, retry_safe=False):
        return self._execute('DELETE', path, payload=payload, retry_safe=retry_safe)

    def list_all(self, path, parameters=None, page_size=MAX_PAGE_SIZE):
        """Walk every page of a list route and return all records.

        Raises rather than returning a partial list: this application acts on
        absence, so code that treats a missing custom field as "not set" and
        then writes would overwrite a value it merely failed to read.
        """
        parameters = dict(parameters or {})
        parameters['limit'] = min(page_size, MAX_PAGE_SIZE)

        collected = []
        reported = None
        page = 1

        while page <= MAX_PAGES:
            parameters['page'] = page
            body = self.get(path, parameters)

            if body.get('object') != 'list':
                raise PopuliApiError(
                    'expected a list object, got %r' % body.get('object'),
                    status_code=200,
                    endpoint=path,
                    populi_type='unexpected_shape',
                )

            echoed = body.get('page')
            if echoed is not None and int(echoed) != page:
                raise PopuliPagingError(path, page, echoed)

            if reported is None:
                reported = body.get('results')

            rows = body.get('data') or []
            collected.extend(rows)

            # Stop on has_more, and on an empty page regardless of what has_more
            # claims — a route that never clears the flag would otherwise walk
            # to the ceiling.
            if not body.get('has_more') or not rows:
                break

            page += 1

        if reported is not None and len(collected) < reported:
            raise PopuliIncompleteReadError(path, len(collected), reported)

        return collected

    # -- internals -------------------------------------------------------

    def _execute(self, method, path, payload=None, retry_safe=False):
        attempt = 0

        while True:
            attempt += 1
            self._pacer.acquire()

            try:
                response = self._send(method, path, payload)
            except (requests.ConnectionError, requests.Timeout) as exc:
                # No response at all, so whether the request was applied is
                # unknowable. status_code is None, which is what marks this
                # apart from every answered failure.
                error = PopuliApiError(
                    '%s produced no response: %s' % (method, exc),
                    status_code=None,
                    endpoint=path,
                )
                if retry_safe and attempt <= self._max_retries:
                    self._backoff(method, path, 'no response', attempt)
                    continue
                raise error from exc

            error = self._error_for(response, path)
            if error is None:
                return self._decode(response, path)

            if self._should_retry(error, retry_safe, attempt):
                if isinstance(error, PopuliRateLimitError):
                    pause = error.retry_after or RATE_LIMIT_PAUSE_SECONDS
                    logger.warning(
                        'populi %s %s: rate limited; pausing %ss (attempt %d/%d)',
                        method, path, pause, attempt, self._max_retries,
                    )
                    self._sleep(pause)
                else:
                    self._backoff(method, path, 'HTTP %s' % error.status_code, attempt)
                continue

            raise error

    def _should_retry(self, error, retry_safe, attempt):
        if attempt > self._max_retries:
            return False

        # A 429 refused the request outright, so nothing was applied and a
        # replay is safe even for a write.
        if isinstance(error, PopuliRateLimitError):
            return True

        # These may or may not have applied a write, so only reads and
        # explicitly-idempotent writes are replayed.
        if error.status_code in RETRYABLE_SERVER_STATUSES:
            return retry_safe

        # Everything else — every 4xx, and any 5xx not listed — says the
        # request itself is wrong or that replaying it would reproduce the
        # fault. Resending unchanged cannot produce a different answer.
        return False

    def _backoff(self, method, path, reason, attempt):
        delay = 2 ** (attempt - 1)
        logger.warning(
            'populi %s %s: %s; retry %d/%d in %ss',
            method, path, reason, attempt, self._max_retries, delay,
        )
        self._sleep(delay)

    def _send(self, method, path, payload):
        url = self.base_url + path.lstrip('/')

        # Populi accepts filter/expand/page/limit either as a JSON body or as a
        # ?parameters= query string and treats them identically — both were
        # measured against the live instance. The body is used here: no
        # URL-length ceiling for a large id filter, the payload stays out of
        # request logs, and it sidesteps the encoding trap where escaping the
        # JSON as a URI rather than a URI *component* corrupts any value
        # containing & = + or #.
        kwargs = {'timeout': self._timeout}
        if payload is not None:
            kwargs['json'] = payload

        return self._session.request(method, url, **kwargs)

    def _error_for(self, response, path):
        """Return an exception for this response, or None if it succeeded.

        Checks the body shape as well as the status, because Populi returns
        error objects under HTTP 200 — the failure worth defending against
        precisely because nothing else about the response looks wrong.
        """
        raw = response.text if response.content else None

        body = None
        if response.content:
            try:
                body = response.json()
            except ValueError:
                body = None

        is_error_object = isinstance(body, dict) and body.get('object') == 'error'

        if response.ok and not is_error_object:
            return None

        populi_code = populi_type = message = None
        if is_error_object:
            populi_code = body.get('code')
            populi_type = body.get('type')
            message = body.get('message')
        elif not response.ok:
            message = (raw or '')[:200] or 'HTTP %s' % response.status_code

        retry_after = self._retry_after(response)

        return self._exception_for(
            message=message or 'request failed',
            status_code=response.status_code,
            endpoint=path,
            populi_code=populi_code,
            populi_type=populi_type,
            was_reported_with_success_status=response.ok and is_error_object,
            raw_body=raw,
            retry_after=retry_after,
        )

    @staticmethod
    def _retry_after(response):
        value = response.headers.get('Retry-After')
        if not value:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            # Retry-After may also be an HTTP date. Falling back to the
            # documented pause is correct and avoids a date parser for a header
            # Populi does not document sending.
            return None

    @staticmethod
    def _exception_for(
        message,
        status_code,
        endpoint,
        populi_code,
        populi_type,
        was_reported_with_success_status,
        raw_body,
        retry_after,
    ):
        common = {
            'status_code': status_code,
            'endpoint': endpoint,
            'populi_code': populi_code,
            'populi_type': populi_type,
            'was_reported_with_success_status': was_reported_with_success_status,
            'raw_body': raw_body,
        }

        # Prefer Populi's own code: a 200 can carry "code": 400, and judging by
        # the transport status alone would call a rejected request healthy.
        effective = populi_code or status_code

        if effective in (401, 403):
            return PopuliAuthError(message, **common)
        if effective == 404:
            return PopuliNotFoundError(message, **common)
        if effective == 429:
            return PopuliRateLimitError(message, retry_after=retry_after, **common)
        return PopuliApiError(message, **common)

    @staticmethod
    def _decode(response, path):
        if not response.content:
            # Some write routes answer 200 with an empty body; a caller that
            # reads returned fields needs a mapping, not None.
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise PopuliApiError(
                'response was not JSON: %s' % (response.text or '')[:200],
                status_code=response.status_code,
                endpoint=path,
                populi_type='invalid_json',
                raw_body=response.text,
            ) from exc

    def __repr__(self):
        return '<PopuliClient %s>' % self.base_url
