# Make schema_generator a proper module
from .suggest import suggest_schema_from_csvs

__all__ = ['suggest_schema_from_csvs']
