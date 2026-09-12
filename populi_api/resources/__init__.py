"""Resource groups, one per Populi route family."""

from .academic_terms import AcademicTerms
from .communication_plans import CommunicationPlans
from .courses import Courses
from .custom_fields import CustomFields
from .data_slicer import DataSlicer
from .files import Files
from .leads import Leads
from .notes import Notes
from .people import People
from .tags import Tags

__all__ = [
    'AcademicTerms',
    'CommunicationPlans',
    'Courses',
    'CustomFields',
    'DataSlicer',
    'Files',
    'Leads',
    'Notes',
    'People',
    'Tags',
]
