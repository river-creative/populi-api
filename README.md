# populi-api

Shared [Populi API2](https://populi.co/api/) client for RMI **Python** applications —
the sibling of the .NET [`Populi.Client`](https://github.com/river-creative/Populi.Client)
and the TypeScript `mp-api`. It mirrors the .NET client's contract deliberately, so a lesson
learned in one transfers to the other rather than having to be learned twice.

## Install

```
pip install "populi-api @ git+https://github.com/river-creative/populi-py.git@<sha>"
```

Pin a commit, not a branch. A branch reference silently changes the dependency on any rebuild,
which is how the project this was extracted from ended up unable to say which client it was
running.

## Use

```python
from populi_api import Populi, PopuliClient
from populi_api.pacing import Pacer

populi = Populi(PopuliClient(
    base_url="https://school.populiweb.com/api2/",   # note /api2/ — see below
    access_key=key,
    pacer=Pacer(utilisation=0.8),
))

person = populi.people.by_student_id("101")
populi.tags.add(person["id"], 471893)
populi.custom_fields.add_option(person["id"], 212516, "admissions", 458237)
```

Resource groups: `people`, `tags`, `custom_fields`, `leads`, `communication_plans`, `notes`.

**Django applications** use the adapter instead, which builds the same object from settings and
holds it process-wide:

```python
from populi_api.integration.django import get_populi
```

It needs `POPULI_BASE_URL` and `POPULI_ACCESS_KEY` in settings, and reads
`POPULI_PACING_UTILISATION` (default 0.8). The client itself imports no Django — verified, not
just intended: constructing one with no settings module configured loads zero `django` modules.
That is what makes this package portable, and it is worth keeping true.

## Populi fails open. Read this before trusting a 200.

Every item below was measured against a live instance, not read in the documentation, and each
one succeeds as far as the caller can see while doing nothing it was asked to do.

- **Adding a tag that does not exist returns success.** No error, no effect. Two stale ids sat in
  a consuming application's config for an unknown length of time, one of which meant a whole
  category of applicant silently never received a required tag. There is no guard available at
  write time — validate ids against `GET /tags`.
- **A checkbox write REPLACES the whole selection.** POSTing one option id to a field holding
  three leaves one row, not four. `add_option` reads the current set and posts the complete
  array for exactly this reason.
- **Row count cannot tell you a field is a checkbox.** One holding exactly one option looks
  single-valued, and a scalar write destroys it. `input_type` decides, and is cached per client.
  The .NET client had this defect and fixed it in v3.0.1.
- **Custom info data is SCOPED** — `person`, `admissions`, `student`, `campuslife`,
  `financial`, `financialaid`, or a term. Reading the wrong scope returns **no rows**, not an
  error, so code that treats absence as "not set" then overwrites. Scope is a required argument
  here; it has no default on purpose.
- **`POST /people/{id}/notes` takes `note`; the read returns `content`.** Sending `content` is
  answered with `Missing required parameter: note`.
- **An option field accepts a label and reports an id.** Writing `"In Progress"` reads back as
  `458178`. Verification compares against both, or every successful write looks like a failure.
- **The tags index lags an add by minutes**, while a remove appears in seconds. `tags.add` does
  not verify by re-reading; Populi's own `"Tag already added"` 400 is the authoritative signal.
- **Error objects arrive with HTTP 200.** On a list route that deserializes to an empty `data`
  array — indistinguishable from "no results". Every response is checked for
  `{"object": "error"}` regardless of status.

## Failures

Everything raises `PopuliApiError` or a subclass: `PopuliAuthError`, `PopuliNotFoundError`,
`PopuliRateLimitError`, `PopuliIncompleteReadError`, `PopuliPagingError`. Members mirror the
.NET client — `status_code` (`None` when no response arrived), `populi_code`, `populi_type`,
`endpoint`, `was_reported_with_success_status`, `raw_body`, and `is_client_error`, which reads
Populi's own code in preference to the HTTP status because a 200 can carry `"code": 400`.

**Paged reads refuse a short read** (`PopuliIncompleteReadError`) rather than returning a partial
list, and check the page echo on every page. Both failures are otherwise silent: a paging
parameter that never reaches Populi returns page 1 forever while looking healthy, and a dropped
page returns a shorter list. Callers act on absence, so a short read is not a smaller answer —
it is a wrong one.

## Rate limits

50 requests/minute 03:00–19:00 Pacific, 100/minute outside, **per API key across every process
using it**. `Pacer` enforces a minimum interval between request *starts* — a concurrency cap is
not a rate limit; five concurrent requests at 200ms is thirty times the daytime budget. The
budget is re-read per request, so a long run widens by itself at the boundary instead of staying
pinned to whichever window it started in.

`utilisation` has no default. The allowance belongs to the key, not to one caller, so a caller
states the share it is taking rather than taking all of it by omission.

## Tests

```
python -m unittest discover -s populi_api/tests -t .
```

No Django, no network, no test runner beyond the standard library — which is the point.

**They are written from Populi's contract, not from this implementation.** That distinction is
not pedantic: the notes bug above shipped with a passing unit test asserting `{'content': ...}`,
because the test checked that the client sent what the client intended to send. A test written
from the implementation cannot discover that the implementation disagrees with the service.
