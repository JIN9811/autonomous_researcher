# Agent and Experimental Packages

Use an Experimental Package to move a validated experiment draft between
workspaces without carrying credentials, private connection values or run
artifacts. Use Agent Package metadata to inspect what is already installed.
Neither operation installs software or starts an experiment. For the ownership
boundaries, see the [modularity guide](../docs/modularity.md).

## Exchange an experiment draft

1. In Runtime IDE, inspect the intended graph and module drafts. Open
   **Infra → Package Manager** to compare installed dependencies with draft
   membership; these are different states.
2. Choose **Export Package** to validate and download the graph, Agent Package
   references and retained module drafts. Include each edited module you need:
   export does not implicitly read referenced module files.
3. At the receiving IDE, choose **Import Package**. Review dependency/version
   errors and confirm replacement of affected dirty drafts only when intended.
   Successful import is a detached draft, not a saved or active configuration.
4. Review graph routes, module settings and unresolved bindings. Configure
   devices, models, storage and services locally through their existing owners;
   a `requires_local_configuration` binding is not a hardware-health result.
5. Use the existing graph/module validation and explicit save/application paths
   for the intended future run. Recheck the active identity and configuration;
   imported package membership alone cannot activate a graph.

The task is complete when the intended detached graph and module drafts are
available with their declared dependencies. If you also intend to apply them,
follow the separate [IDE activation workflow](../docs/runtime/runtime_ide.md#operator-workflow).
Do not interpret successful exchange as readiness or execution approval.

## Installed package membership

Agent Packages are installed metadata, not an installer. Shipped manifests in
`packages/agents/` are loaded only when their matching code-owned agent module
is registered. Current owner packages are Design, Specimen, Vision,
Manipulation, Equipment, Analysis and BO. BO and Design have no bridge;
Specimen references the single installed `printer_fleet@1.0.0`, and other
owners retain the dependencies declared by their manifests. References use
exact numeric `major.minor.patch` versions. Python distribution data includes
these manifests and the provider requirements/READMEs.

The injected `PackageService` exposes `catalog()`, `export_experimental(payload)`
and `import_experimental(payload)`. It owns no store or runtime. Graph validation
uses the existing `ATRLangGraphCompiler`; module validation uses the host's
existing `ModuleConfigStore` normalization and module/execution-graph validator.
Validation can compile structure, but never invokes handlers or starts a graph.

## HTTP contract

This section is for API clients implementing the same exchange. Validation may
compile structure but never runs handlers. Treat `ok` and the returned
`activated`/`persisted` fields as separate from HTTP transport success.

`GET /api/packages` returns `{ok, schema: "ax4lab.package_catalog.v1", errors,
agent_packages, bridge_modules, external_requirements, limits}`. Agent items
contain `id`, `version`, `agent_module`, `handler`, `module_reference`,
`bridge_modules: [{id,version}]` and `ownership` (frontend/configuration/storage).
Bridge items include code-owned IDs/versions/tools, provider component references,
UI/storage references, `binding_requirements`, and
`package_owners: [{id,version}]`. This is installed membership; an IDE marks
current draft membership separately. Catalog reads no device memory.

### Export a detached package

POST directly to `/api/packages/experimental/export` with:

```json
{
  "schema": "ax4lab.experimental_package.v1",
  "id": "my_experiment",
  "version": "1.0.0",
  "graph": {},
  "agent_packages": [{"id": "design", "version": "1.0.0"}, {"id": "specimen", "version": "1.0.0"}],
  "module_configurations": {},
  "bindings": []
}
```

Replace `graph` with the current existing graph configuration; it is required
to pass existing graph validation. `module_configurations` maps module ID to
`{"module": <existing module configuration>}`. Include each edited module draft
the IDE intends to retain. Export never implicitly opens referenced module files.

An optional `display_name` provides a human-readable package name independently
of `graph.name`. On import, the IDE draft carries package ID, version and display
name in `graph.metadata.experimental_package`; only the existing explicit
save/activation path makes this identity active. Live Setup reads that identity,
never infers a package name from the graph, and shows `Not bound` when absent.
Existing declarative `modules/design`, repository-relative source references and
local API/UI routes are retained as data.

Knowledge and Guardian module configurations may contain one optional strict
`module.owner_plan` declaration. It travels only inside the existing
`module_configurations` map; there is no second Package-level plan copy. Import
hydrates a detached draft. The Package Manager's separate **Validate Draft** and
**Apply for Future Runs** actions use the existing module APIs, and only explicit
apply can change the active module configuration for a later run.

Export computes `bridge_modules: [{id,version}]` and
`external_owners: [{handler,module_id}]`. External owners explicitly capture
installed legacy/core graph handlers and module IDs; they have no invented
Agent Package or version. Selected Agent Packages need not cover the whole graph.
Duplicated references and missing/version-conflicting dependencies fail atomically.

Export returns `{ok,errors,package,activated:false,persisted:false}`. Known runtime
and credential fields are removed; machine-local paths, connection URLs and code
or file-inclusion fields fail validation. These guards do not classify arbitrary
secrets hidden in free text; do not enter credentials in prompts or notes.

### Import and resolve local bindings

POST that `package` object directly to `/api/packages/experimental/import`.
Import rejects private fields and checks exact installed dependencies, all graph
handlers and all supplied module configurations with the existing validators.
It returns `{ok,errors,draft,unresolved_bindings,activated:false,persisted:false}`.
`draft` is the whole detached package, including `graph` and
`module_configurations`. Keep both in IDE memory until a separately authorized
existing save action. No store writes, module loading, graph activation, tool
calls or credential reads happen during import/export.

Bindings contain only `{id,kind,owner_id,required}`. Kinds are `device`, `model`,
`storage`, or `service`; values and credentials are forbidden. Fleet adds the
required `printer_fleet_connection` device binding. All supplied/required bindings
return unresolved with `status: "requires_local_configuration"`; this is not an
assertion about current hardware state.

### Interpret validation failures

Validation failure uses HTTP 200 with `ok:false`, `errors:[message]` and
`package:null` or `draft:null` (import also returns `unresolved_bindings:[]`).
Malformed JSON, duplicate JSON keys and nonfinite JSON use HTTP 400; payloads
over 1,048,576 bytes use HTTP 413. Parsing is streamed and bounded; nesting is
limited to 40. Messages omit private values. Unknown top-level/schema fields,
executable fields, connection fields and non-exact versions fail closed.

## Inspect dependencies without executing them

In Runtime IDE, **Device Bridge Plane** (graph or Explorer) and **Infra → Device
Bridges** open the same contract graph: Agent Package nodes connect to Device
Bridge nodes. Double-click a bridge to inspect its internal components in a
separate graph tab. Both levels reuse the standard IDE canvas and Inspector.
Package contracts are not device bridges. **Infra →
Package Manager** separately hosts membership, dependencies and package exchange.
Printer Fleet is one bridge package containing Bambu and Prusa providers.
The current Orchestration graph is shown as a reference rather than copied into
a Knowledge or Guardian declaration.
Back returns from bridge internals to the plane, then to the prior
graph or agent tab without replacing its draft or Dry-run Trace output.

Removing composition references only changes a detached package. Installed
agents, bridges, private configuration, active graphs and artifact storage remain
owned by their existing components; this API provides no removal or install action.
