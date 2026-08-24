"""Makes `import mmos_client` work when pytest is run against this package without
installing it into the shared venv (see handoff/a4-integration.md for why)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
