#!/usr/bin/env python
"""Django-ийн command-line удирдлагын хэрэгсэл."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django импортлож чадсангүй. Virtualenv идэвхжсэн эсэхийг, "
            "мөн PYTHONPATH-г шалгана уу."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
