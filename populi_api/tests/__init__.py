"""Tests for the Populi API2 client.

Plain ``unittest`` with no Django dependency, matching the client itself: they
run under ``manage.py test`` because Django's runner uses unittest discovery,
and they would run under bare ``unittest`` just as well. That is the point — a
client that needed a settings module to test could not be lifted into its own
package.
"""
