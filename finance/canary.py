"""Facade re-exporting canary functionality from finance.interface.canary."""

from finance.interface import canary as _canary
from finance.interface.canary import *

_digits = _canary._digits
_phone = _canary._phone
_identity = _canary._identity
_matches = _canary._matches
_SALT = _canary._SALT
