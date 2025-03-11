from pathlib import Path
import sys

TESTS_DIR = Path(__file__).parent

sys.modules["vim"] = {} # mock vim module
sys.path.append(str(TESTS_DIR.parent / "python")) # add the plugin to the path
