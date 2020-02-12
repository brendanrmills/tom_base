#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    import numpy
    print(numpy.__version__)
    import astropy
    print(astropy.__version__)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tom_base.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        )
    execute_from_command_line(sys.argv)
