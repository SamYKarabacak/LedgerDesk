# Third-party components

LedgerDesk's application code and native launcher use the MIT license in
LICENSE. The portable Windows package additionally contains the following
unmodified runtime components and their own license notices:

- **CPython 3.14.8**, distributed by the Python Software Foundation. The full
  notices are preserved in `runtime/LICENSE.txt`, along with runtime library
  notices supplied in that distribution.
- **Tcl/Tk 9.0.4** and its supporting libraries, from the matching official
  CPython Windows installer. Tcl/Tk script archives and their notices are
  preserved in `runtime/tcl/`. CPython's license collection also describes
  included third-party components. The build copies any `license.terms` files
  from the Tcl/Tk script archives into `runtime/licenses/` for easy access.
- **Microsoft Visual C++ runtime libraries** shipped with the official
  CPython distribution, under their upstream redistribution terms.

The native launcher is compiled using MinGW-w64. Its relevant runtime license
notice is included at `runtime/licenses/MinGW-w64-COPYING` when provided by
the build toolchain. The compiler itself is not shipped with the application.

Sources and exact runtime download hashes are recorded in
`packaging/windows/runtime.lock.json` in the repository and `BUILD_INFO.json`
in the portable package. The builder verifies both downloads before extraction.

Upstream references:

- https://www.python.org/downloads/release/python-3148/
- https://www.python.org/ftp/python/3.14.8/windows-3.14.8.json
- https://docs.python.org/3.14/using/windows.html
- https://www.tcl-lang.org/software/tcltk/license.html
- https://www.mingw-w64.org/
