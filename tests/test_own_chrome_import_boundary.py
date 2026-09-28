"""Contract with the own-chrome maintainer (team lead, Phase 2): after this
package absorbs the `li` messaging surface, linkedin_mcp may import ONLY
own_chrome.cdp -- never any other own_chrome submodule. Anything else `li`
depended on (actions, popups, workflow, intent, tab choosing) had to be
copied into linkedin_mcp (see messages_actions.py, messaging.py) rather than
imported. This test fails the build if that boundary is ever crossed.
"""

from __future__ import annotations

import ast
import pathlib

import linkedin_mcp

PACKAGE_DIR = pathlib.Path(linkedin_mcp.__file__).parent


def _own_chrome_imports(py_file: pathlib.Path) -> list[str]:
    """Return every module path imported from own_chrome by this file, e.g.
    'own_chrome.cdp' for `from own_chrome.cdp import evaluate` and
    `import own_chrome.cdp`, or 'own_chrome' for a bare `import own_chrome`."""
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("own_chrome"):
            found.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("own_chrome"):
                    found.append(alias.name)
    return found


def test_only_own_chrome_cdp_is_imported_anywhere_in_the_package() -> None:
    violations: dict[str, list[str]] = {}
    for py_file in PACKAGE_DIR.rglob("*.py"):
        imports = [mod for mod in _own_chrome_imports(py_file) if mod != "own_chrome.cdp"]
        if imports:
            violations[py_file.name] = imports
    assert violations == {}, f"only own_chrome.cdp may be imported; found: {violations}"
