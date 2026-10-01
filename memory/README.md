# Local Memory Files

This directory stores local operator/device memory such as printer credentials,
Windows bridge endpoints, robot port mappings, and temporary resume notes.

Generated state is ignored by Git because it can contain secrets, IP addresses,
hardware-specific state, or machine-local calibration data. The Python modules
already tracked here are compatibility source code; `.gitignore` explicitly
retains `memory/*.py` and this README.

Keep runtime data private. Review source changes normally, and follow the
[publication boundary](../docs/knowledge/publication.md) before exporting evidence.
