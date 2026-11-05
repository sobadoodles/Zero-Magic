"""A throwaway database must be selected BEFORE any application import.

Replace the old tests/conftest.py (which only cleared in-memory dictionaries).
Never run tests using the real workspace database.
"""
import os
import sys
import tempfile
from pathlib import Path

if 'app.storage' in sys.modules:
    raise RuntimeError('Application imported before test database selection. Restart pytest.')
_TEST_DIR=tempfile.TemporaryDirectory(prefix='zero-magic-pytest-')
os.environ['ZERO_MAGIC_DB']=str(Path(_TEST_DIR.name)/'workspace.sqlite3')

os.environ["ALLOWED_HOSTS"]="localhost,127.0.0.1,testserver"
