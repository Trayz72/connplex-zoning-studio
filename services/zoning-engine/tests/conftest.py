import os
import sys

# These modules use bare imports (e.g. `import rules_registry`), matching how
# main.py itself is run (uvicorn invoked with this directory as cwd) — tests
# need the same directory on sys.path regardless of where pytest is invoked
# from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
