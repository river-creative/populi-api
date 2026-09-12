"""Test doubles for the Populi transport.

A fake ``requests.Session`` rather than a mocking library: the client's contract
with requests is three attributes wide, and a hand-written double makes the
recorded calls — which is what most of these tests actually assert on — plain to
read.
"""

import json as jsonlib

import requests


class FakeResponse:
    """The slice of ``requests.Response`` the client actually touches."""

    def __init__(self, status_code=200, body=None, headers=None, text=None):
        self.status_code = status_code
        self.headers = headers or {}

        if text is not None:
            self.text = text
            self._body = None
            self._raw = text
        elif body is None:
            self.text = ''
            self._body = None
            self._raw = ''
        else:
            self._body = body
            self._raw = jsonlib.dumps(body)
            self.text = self._raw

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    @property
    def content(self):
        return self._raw.encode() if self._raw else b''

    def json(self):
        if self._body is None:
            raise ValueError('no json')
        return self._body


class FakeSession:
    """Returns queued responses and records every call.

    ``responses`` may contain ``FakeResponse`` objects or exceptions; an
    exception is raised instead of returned, which is how transport failures
    are simulated.
    """

    def __init__(self, responses):
        self.headers = {}
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({'method': method, 'url': url, **kwargs})

        if not self._responses:
            raise AssertionError(
                'unexpected request %s %s — the double ran out of responses'
                % (method, url)
            )

        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def connection_error():
    return requests.ConnectionError('connection reset')


def timeout_error():
    return requests.Timeout('timed out')


def list_body(rows, page=1, results=None, has_more=False):
    """A Populi list envelope.

    ``count`` is deliberately set to the length of THIS page while ``results``
    is the across-all-pages total — the distinction that a paging check written
    against the wrong one silently gets wrong.
    """
    return {
        'object': 'list',
        'count': len(rows),
        'results': len(rows) if results is None else results,
        'page': page,
        'pages': 1,
        'has_more': has_more,
        'data': rows,
    }


def error_body(code=400, error_type='invalid_parameter', message='bad request'):
    return {
        'object': 'error',
        'code': code,
        'type': error_type,
        'message': message,
    }
