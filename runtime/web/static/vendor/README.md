# Locally hosted field renderer

`vtk-34.15.4.js` is the vtk.js 34.15.4 browser bundle, downloaded from
https://unpkg.com/vtk.js@34.15.4/vtk.js. Its license is preserved in
`vtk-Copyright.txt` (https://unpkg.com/vtk.js@34.15.4/Copyright.txt).
The retained field-result template references this local bundle rather than a
CDN. That template is historical: the current main application no longer exposes
the retired CAE workspace routes. Keeping the bundle and license does not mean
that a solver or CAE workflow is active; see the
[measurement-only Analysis reference](../../../../system/agents/analysis_agent.md).
