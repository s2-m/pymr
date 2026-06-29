"""Put the launcher directory on sys.path so tests can import the shared module
(`_pymr_common`) the same way the `pymr`/`pyml` scripts do at runtime."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bin")))
