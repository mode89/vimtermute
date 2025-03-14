python3 << EOF
import vim

from pathlib import Path
PLUGIN_ROOT = Path(vim.eval("expand('<sfile>')")).parent.parent

import sys
sys.path.append(str(PLUGIN_ROOT / "python"))

import vimtermute
EOF

function! VimtermuteDoAsyncCall(timer)
    python3 vimtermute.do_async_call()
endfunction
