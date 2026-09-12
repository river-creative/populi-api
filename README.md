# populi-api

A Populi API2 client for Python.

Populi's API fails open in a number of places — a request it cannot read is answered with
HTTP 200 and quietly ignored. This client is built around that: the behaviours documented
below were each a defect before they were a paragraph, measured against a live instance
rather than read in the reference.

## Install

```
pip install populi-api
```

Requires Python 3.9+ and `requests`. Nothing else — the Django adapter is optional and imports
Django only if you use it.

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
populi.tags.add(person["id"], 700010)
populi.custom_fields.add_option(person["id"], 900010, "admissions", 500010)
```

### What it covers

| Group | |
|---|---|
| `people` | get, list (filtered), `by_student_id`, `by_student_ids` (bulk), `with_role`, update, online payment link |
| `tags` | list, add, remove |
| `custom_fields` | read/write per scope, checkbox options, field definitions, term-scoped data |
| `leads` | list, current, current status, set status |
| `notes` | list, create |
| `communication_plans` | list, delete |
| `academic_terms` | list, get, current |
| `courses` | offerings, assignments, rosters, grades (set / excuse / clear) |
| `files` | download, presigned download link, profile picture upload |
| `data_slicer` | list reports, pull results |

Plus `populi.test_connection()` and `populi.with_pacing(0.8)`.

### Filters

Populi filters **fail open** — a condition it cannot read is discarded and the request answers
200 with the entire unfiltered list. Build them rather than writing the JSON:

```python
from populi_api import PopuliFilter

people = populi.people.list(
    PopuliFilter().all_of().where_custom_field(212516)      # has an answer
)
```

`PopuliFilter` refuses an empty filter and an empty group, because Populi ignores both and an
ignored filter matches everyone. It cannot check a condition *name* against a route, so verify a
new filter against the live API and confirm the result set actually **narrowed** — a query
returning more than you expected is the signature of a dropped condition.

The reliable way to discover a shape is Populi's own UI: build the filter on an index page, save
it as a preset, edit the preset, and use **"Show JSON for API"**.

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

- **Adding a tag that does not exist returns success.** No error, no effect. A stale id in a caller's config is not an
  error anywhere — it is an automation that silently stops applying a tag, for as long as nobody
  notices the absence. There is no guard available at
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
- **Assignment grades take POINTS and answer in PERCENT.** Write 1 to a 1-point assignment and
  Populi replies `grade: 100`, so a verifying read comparing against what it sent fails on every
  success. Excusing is the *grade* `"E"` — the route also takes an `excused` parameter, returns
  200, and ignores it.
- **An `expand` Populi does not recognise is dropped, still answering 200.** A missing `options`
  key therefore means "not honoured", never "this field has none".

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

## Licence

MIT. See [LICENSE](LICENSE).

## Tests

```
python -m unittest discover -s populi_api/tests -t .
```

No Django, no network, no test runner beyond the standard library — which is the point.

**They are written from Populi's contract, not from this implementation.** That distinction is
not pedantic: the notes bug above shipped with a passing unit test asserting `{'content': ...}`,
because the test checked that the client sent what the client intended to send. A test written
from the implementation cannot discover that the implementation disagrees with the service.
