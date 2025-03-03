python3 << EOF
import vim

from pathlib import Path
PLUGIN_ROOT = Path(vim.eval("expand('<sfile>')")).parent.parent

import sys
sys.path.append(str(PLUGIN_ROOT / "python"))

import vimtermute
EOF

command! -nargs=0 VimtermuteChat :python3 vimtermute.chat()
command! -nargs=0 VimtermuteAsk :python3 vimtermute.ask()
