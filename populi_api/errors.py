"""Exception types for the Populi API2 client.

Deliberately mirrors the contract of the .NET `Populi.Client`
(github.com/river-creative/Populi.Client), which is the established shared
client for RMI applications. The member names are the Python spelling of the
same concepts — `status_code`, `populi_code`, `populi_type`, `endpoint`,
`was_reported_with_success_status`, `raw_body`, `is_client_error` — so that the
two clients can be reasoned about together and a lesson learned in one transfers
to the other. Inventing a parallel vocabulary for identical behaviour would cost
that for nothing.

The single type covers three situations that a caller must be able to tell
apart, which is why the distinguishing information is on the exception rather
than in the class hierarchy:

* Populi rejected the request (``is_client_error``) — never retryable;
* Populi failed to serve it, or never answered (``status_code is None``) —
  retryable, subject to whether replaying the request is safe;
* Populi answered successfully with something untrustworthy — a short read, or
  a page echo that does not match what was asked for.

That last group is the reason this module exists at all. Populi's failure modes
are mostly silent: a dropped filter condition, a lost page, or an error object
returned under HTTP 200 all look like ordinary success, and the caller then acts
on the wrong data.
"""


class PopuliError(Exception):
    """Base class. Catching this catches every failure this client raises."""


class PopuliConfigurationError(PopuliError):
    """The client was constructed without something it cannot work without.

    Raised at construction rather than on first use, so a misconfigured
    deployment fails while starting instead of on the first webhook.
    """


class PopuliApiError(PopuliError):
    """A Populi call that failed — by HTTP status, by error object, or by not answering.

    Populi returns error objects with **HTTP 200**::

        {"object":"error","code":400,"type":"missing_parameter",
         "message":"Missing required parameter: academic_term_id"}

    Checking the status alone therefore misses a whole class of failure.
    Deserialized into a list response such a body yields an empty ``data``
    array — indistinguishable from "no results" at the call site, which is how
    a failed call gets mistaken for an empty one.

    ``status_code`` is the HTTP status; 200 for a 200-with-error-body, and
    **None when the request never produced a response at all** (socket failure,
    timeout). A caller distinguishes "this request is wrong" from "Populi is
    unwell" with ``is_client_error`` rather than by inspecting statuses.
    """

    def __init__(
        self,
        message,
        status_code=None,
        endpoint=None,
        populi_code=None,
        populi_type=None,
        was_reported_with_success_status=False,
        raw_body=None,
    ):
        # Populi's own message, kept unadorned. The composed string below adds
        # the endpoint for a log line, which makes it the wrong thing to match
        # on — and matching on it is necessary: "Tag already added" arrives as
        # a 400 and is the authoritative confirmation that a tag write landed.
        self.message = message
        self.status_code = status_code
        self.endpoint = endpoint
        self.populi_code = populi_code
        self.populi_type = populi_type
        self.was_reported_with_success_status = was_reported_with_success_status
        self.raw_body = raw_body

        super().__init__(
            '%s%s%s' % (
                message,
                ' [%s]' % endpoint if endpoint else '',
                ' (reported with a success status)' if was_reported_with_success_status else '',
            )
        )

    @property
    def effective_code(self):
        """Populi's own error code where it gave one, otherwise the HTTP status.

        The two do not always agree: an error object can arrive with HTTP 200
        carrying ``"code": 400``, and judging that by the transport status alone
        would call a rejected request healthy.
        """
        if self.populi_code:
            return self.populi_code
        return self.status_code or 0

    @property
    def is_client_error(self):
        """True when Populi rejected the REQUEST rather than failing to serve it.

        Resending such a request unchanged cannot produce a different answer, so
        this is what callers and the retry policy branch on instead of treating
        every failure alike.

        False when neither code is available — a transport failure has no answer
        to classify, and a short read is not a rejection either.
        """
        return 400 <= self.effective_code < 500


class PopuliAuthError(PopuliApiError):
    """401/403 — the key is wrong, malformed, or lacks the required role.

    Separated because it is never transient and because it is the failure this
    client was written to fix: an API2 key sent to the legacy API answered
    exactly this way for weeks without anyone noticing.
    """


class PopuliNotFoundError(PopuliApiError):
    """404 — no such route, or no such record.

    Worth distinguishing: for a show route it is frequently an expected outcome
    ("this person has no such row") rather than a fault.
    """


class PopuliRateLimitError(PopuliApiError):
    """429 — the key's request budget is spent.

    Populi's documented remedy is to pause *just over a minute* so the window is
    guaranteed to have reset, which is a different shape from the short
    exponential backoff used for 502/503/504. ``Retry-After`` is not mentioned
    anywhere in Populi's documentation; it is honoured when present, but the
    minute-plus pause is the real contract rather than the fallback.
    """

    def __init__(self, *args, retry_after=None, **kwargs):
        self.retry_after = retry_after
        super().__init__(*args, **kwargs)


class PopuliIncompleteReadError(PopuliApiError):
    """A paged read collected fewer records than Populi said the query matched.

    Raised rather than returning the short list, because at the call site a
    short read and "there is nothing there" are the same empty list — and this
    application acts on absence. Code that treats a missing custom field as "not
    set" and then writes would overwrite a value it merely failed to read.

    Transient, and ``is_client_error`` is False, so it is worth retrying. Only a
    SHORT read is an error: collecting more than reported just means rows were
    added while paging, which cannot turn a present value into an absent one.

    The comparison is against the across-all-pages total (``results``), never
    ``count``, which is *this page* — a check written against ``count`` is
    capped at the page size and silently stops working once a result set fills
    one page, which is exactly when it is needed.
    """

    def __init__(self, endpoint, collected, reported):
        self.collected = collected
        self.reported = reported
        super().__init__(
            'incomplete read: collected %d of %d reported records'
            % (collected, reported),
            endpoint=endpoint,
        )


class PopuliPagingError(PopuliApiError):
    """Populi echoed a different page than the one requested.

    The cheapest available guard against a paging parameter that is not reaching
    Populi. When that happens every request returns page 1, the loop cannot
    terminate, and rows pile up as duplicates — which from the outside looks
    exactly like healthy paging. The echo is the only signal that distinguishes
    them, and it catches the fault on the first wrong page.
    """

    def __init__(self, endpoint, requested, echoed):
        self.requested = requested
        self.echoed = echoed
        super().__init__(
            'paging not honoured: asked for page %s, got page %s' % (requested, echoed),
            endpoint=endpoint,
        )
