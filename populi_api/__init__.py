"""A Populi API2 client.

Plain Python: nothing in this package imports Django or reads settings. The
Django adapter lives in ``populi_api.integration.django`` and is the only module
that knows this project exists, so the package can be lifted into its own
repository — alongside the .NET ``Populi.Client`` and the TypeScript ``mp-api``
— without rewriting its constructor, its tests or its call sites.

Typical use::

    from populi_api import Populi, PopuliClient
    from populi_api.pacing import Pacer

    populi = Populi(PopuliClient(
        base_url='https://school.populiweb.com/api2/',
        access_key=key,
        pacer=Pacer(utilisation=0.8),
    ))

    person = populi.people.by_student_id('101')
    populi.tags.add(person['id'], 700010)

In this project, use ``populi_api.integration.django.get_populi()`` instead,
which builds the same object from Django settings.
"""

from .client import PopuliClient
from .errors import (
    PopuliApiError,
    PopuliAuthError,
    PopuliConfigurationError,
    PopuliError,
    PopuliIncompleteReadError,
    PopuliNotFoundError,
    PopuliPagingError,
    PopuliRateLimitError,
)
from .filters import PopuliFilter
from .resources import (
    AcademicTerms,
    CommunicationPlans,
    Courses,
    CustomFields,
    DataSlicer,
    Files,
    Leads,
    Notes,
    People,
    Tags,
)

__all__ = [
    'Populi',
    'PopuliClient',
    'PopuliFilter',
    'PopuliError',
    'PopuliApiError',
    'PopuliAuthError',
    'PopuliConfigurationError',
    'PopuliIncompleteReadError',
    'PopuliNotFoundError',
    'PopuliPagingError',
    'PopuliRateLimitError',
]


class Populi:
    """The resource groups, sharing one transport.

    A thin facade rather than a god object: it owns no behaviour, so the
    transport stays testable on its own and each resource group stays readable
    against one section of Populi's reference. Every group shares the same
    client, and therefore the same pacer — which matters, because the request
    budget belongs to the key, not to any one caller.
    """

    def __init__(self, client):
        self.client = client
        self.people = People(client)
        self.tags = Tags(client)
        self.custom_fields = CustomFields(client)
        self.leads = Leads(client)
        self.communication_plans = CommunicationPlans(client)
        self.notes = Notes(client)
        self.academic_terms = AcademicTerms(client)
        self.courses = Courses(client)
        self.files = Files(client)
        self.data_slicer = DataSlicer(client)

    def test_connection(self):
        """Whether the credentials work and the endpoint answers.

        Reads one page of one small route. Returns True or raises — it does not
        return False, because every reason this can fail is worth seeing: a
        malformed key, a key for the wrong API, an endpoint missing its /api2/
        suffix, and "the network is down" are four different problems and a
        bare False makes them one.
        """
        self.client.get('academicterms', {'limit': 1})
        return True

    def with_pacing(self, utilisation):
        """A Populi whose requests claim ``utilisation`` of the key's budget."""
        return Populi(self.client.with_pacing(utilisation))

    def __repr__(self):
        return '<Populi %s>' % self.client.base_url
