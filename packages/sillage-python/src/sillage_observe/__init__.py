"""Explicit, process-local Sillage instrumentation. Import has no side effects."""
from .configuration import Configuration, ConfigurationError
from .instrumentation import Instrumentation

__version__ = "0.2.0"
__all__ = ["Configuration", "ConfigurationError", "Instrumentation", "__version__"]
