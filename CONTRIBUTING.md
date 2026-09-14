# Contributing

Contributions are welcome, particularly ones that add a route this client does not cover yet or
correct something it gets wrong about Populi.

By submitting a contribution you agree it is licensed under the Apache License 2.0, the same terms
as the project — that is [section 5](LICENSE) of the licence and requires nothing extra from you.

## Running the tests

```
python -m unittest discover -s populi_api/tests -t .
```

No Django, no network, no test runner beyond the standard library. They should stay that way: a
client that needs a framework or an internet connection to test is one nobody runs the tests for.

## The one rule that matters

**Write tests from Populi's contract, not from the implementation.**

This is not style advice. A bug shipped here where the client sent `{"content": ...}` to a route
that requires `{"note": ...}`, and the unit test asserting `{"content": ...}` passed the entire
time — because it checked that the client sent what the client intended to send. Notes were never
created, the error was swallowed by the caller, and it was only found by driving a real request.

If you are adding a route, say in the test **why Populi behaves that way**, and verify it against a
real instance before trusting it.

## Populi fails open — assume nothing from a 200

Most of the defensive code here exists because a request Populi cannot read is answered with HTTP
200 and quietly ignored. Before changing or removing a guard, check the README section on this:
each item listed there was a defect first, and several look like needless complexity until you know
what they prevent.

In particular, please do not "simplify":

- the client-side re-check on filtered bulk lookups
- the page echo check, or the refusal to return a short paged read
- the `input_type` lookup that decides whether a custom field is multi-valued
- the error-object check on 2xx responses

Each has a comment explaining the failure it catches. If one of them is genuinely wrong, the
comment is the thing to argue with.

## Adding a route

1. Put it in the resource group that matches Populi's route family, or add a new module if there
   isn't one.
2. Document anything the reference gets wrong or omits, in the docstring, with what you measured.
3. Add tests covering the behaviour that would be silently wrong, not the happy path.
4. Update the README table and the CHANGELOG.

## Releasing

Maintainers only, and tag-driven — see [RELEASING.md](RELEASING.md). The rule that catches people
out is that the tag and the version in `pyproject.toml` must agree exactly; the workflow refuses a
mismatch before it builds.

## Reporting something

An issue that names the route, what you sent, and what Populi answered is worth more than a
description of the symptom — this API's failures are mostly indistinguishable from success at the
call site, so the raw exchange is usually the whole diagnosis.
