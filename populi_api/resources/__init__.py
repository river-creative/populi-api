"""Resource groups, one per Populi route family."""

from .communication_plans import CommunicationPlans
from .custom_fields import CustomFields
from .leads import Leads
from .notes import Notes
from .people import People
from .tags import Tags

__all__ = [
    'CommunicationPlans',
    'CustomFields',
    'Leads',
    'Notes',
    'People',
    'Tags',
]
