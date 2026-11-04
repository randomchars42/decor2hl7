"""Terminal output of messages constructed in the selected language."""
from __future__ import annotations
import sys


def say(message: str) -> None:
    print(message, file=sys.stderr)


def out(message: str) -> None:
    print(message)
