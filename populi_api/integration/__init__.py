"""Framework adapters.

Everything above this package is plain Python. Adapters live here so that a
framework dependency is opt-in: importing ``populi_api`` never imports Django,
which is what keeps the client testable without a settings module and portable
to its own repository.
"""
