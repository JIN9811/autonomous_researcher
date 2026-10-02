# GitHub Version Control Layout

This repository separates versioned system files from local user/runtime files.

## Versioned System Files

Commit source code, reusable configuration, deployment manifests, tests, docs,
installation scripts, prompts, web UI assets, and deterministic diagram sources.

Primary tracked directories:

- `agents/`
- `app/`
- `backends/`
- `configs/`
- `deploy/`
- `device_bridges/`
- `docs/`
- `image/`
- `install/`
- `knowledge/`
- `learning/`
- `logging_system/`
- `mcp_tools/`
- `orchestrator/`
- `policies/`
- `submodules/`
- `tests/`
- `utils/`
- `web/`

## Local User and Runtime Files

Do not commit private or generated runtime data. Generated contents of these
folders are ignored; their README files and explicitly tracked source modules
are retained. In particular, `memory/` also contains versioned Python
compatibility modules, not only private state:

- `memory/`
- `runs/`
- `artifacts/`
- `outputs/`
- `user_files/`

Examples of ignored files:

- `.env`
- printer or Windows bridge connection JSON files
- generated STL/G-code/3MF files
- run logs
- LeRobot datasets and checkpoints
- local virtual environments

## First Commit Policy

Before pushing to GitHub:

1. Run `git status --short` and inspect `git diff --cached`.
2. Confirm secrets are not staged.
3. Confirm large generated artifacts are not staged.
4. Commit only source, docs, reusable config, templates, and reviewed lightweight assets.
5. Follow the [publication checks](../knowledge/publication.md) for evidence,
   Wiki material and screenshots. Ignored local data is not a public artifact link.

## Branch Use Policy

Avoid unnecessary branch proliferation. Use a branch when the operator explicitly
asks for branch work, when a change is risky, or when a change may take multiple
iterations before it is known-good.

Use branch workflow for:

- operator request such as "make a branch", "work on a branch", or "do this separately"
- large GUI refactors
- hardware-control workflow changes
- model-serving / vLLM / Docker / Kubernetes changes
- experimental algorithm changes
- changes that may need rollback or comparison

Small documentation edits, typo fixes, and clearly safe single-file changes may
be committed directly on `main` after inspection.

Branch workflow:

1. Start from a clean `main`.
2. Create a dedicated branch before editing:

   ```bash
   git checkout main
   git pull
   git checkout -b <work-branch-name>
   ```

3. Make changes on that branch.
4. Run the relevant non-hardware tests. Live equipment checks require separate
   operator authorization and must not be started merely to prepare a commit.
5. Commit the branch work:

   ```bash
   git status
   git add <reviewed-paths>
   git commit -m "<clear change summary>"
   ```

6. Merge into `main` only after the updated system works as expected:

   ```bash
   git checkout main
   git merge <work-branch-name>
   git push
   ```

7. If verification fails, preserve the branch and diagnose it. Do not force-delete
   unmerged work or overwrite a dirty worktree. After integration, an explicitly
   requested cleanup can use `git branch -d <work-branch-name>`; Git then refuses
   to delete an unmerged branch.

Recommended branch names:

- `dev`
- `feature-<short-topic>`
- `fix-<short-topic>`
- `experiment-<short-topic>`

Use `main` as the latest known-good version. If the operator explicitly says to
use a branch, create one before editing.
