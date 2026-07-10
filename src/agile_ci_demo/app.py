import os
import sys

# Get the directory where app.py lives (src/agile_ci_demo/)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Move up one level to get to the 'src/' folder directory path
SRC_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))

# Inject the paths into the system path so both 'main' and 'job_portal' resolve
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
    
# Also inject the main workspace directory just in case Pylance checks the project root
WORKSPACE_ROOT = os.path.abspath(os.path.join(SRC_DIR, ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

# Now Python and Pylance can cleanly navigate package frameworks from the src/ scope
from main import app

__all__ = ["app"]