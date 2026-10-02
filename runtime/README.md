# Autonomous Researcher runtime

This directory contains the `autonomous-researcher` Python build project and
its executable peers. `runtime` is a filesystem container, not a Python import
namespace. Public imports such as `app`, `graphs`, and `utils` are unchanged.

From the outer repository, install with `python -m pip install -e './runtime[dev]'`.
Run source commands from this directory using the outer `.venv` interpreter.
Build distributions here with `python -m build --no-isolation`.

The outer repository owns Git, `.github`, `.env`, `.venv`, `system`, and private
store bindings. `configs/repository_layout.json` names the source roots; explicit
`ATR_LAYOUT_CONFIG` and `ATR_PATH_BINDINGS` bindings support installed use.
Moving sources never activates new private stores.

`distribution-files.json` positively enumerates wheel code/resources and the
broader sdist delivery surface. Wheel resources under
`_autonomous_researcher_resources` can be copied into an explicitly bound runtime
tree. Optional Piper voice assets are source/sdist delivery only, not wheel
contents. The standalone Windows bridge retains its own environment, portable
Python and data-root contracts.

See [installation](install/README.md), [repository navigation](../README.md),
and [license](LICENSE).
