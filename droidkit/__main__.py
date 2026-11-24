# SPDX-License-Identifier: Apache-2.0
"""Entry point for ``python -m droidkit`` and the ``droidkit`` console script."""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
