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
- `gui/`
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

Do not commit private or generated runtime data. These folders are intentionally
ignored except for their README files:

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

1. Run `git status --ignored`.
2. Confirm secrets are not staged.
3. Confirm large generated artifacts are not staged.
4. Commit only source, docs, reusable config, templates, and lightweight assets.

## Branch-First Development Policy

Do not modify `main` directly for feature work, experiments, hardware workflow
changes, model-serving changes, or GUI refactors.

Required workflow:

1. Start from a clean `main`.
2. Create a dedicated branch before editing:

   ```bash
   git checkout main
   git pull
   git checkout -b <work-branch-name>
   ```

3. Make changes only on that branch.
4. Run the relevant tests or live checks.
5. Commit the branch work:

   ```bash
   git status
   git add .
   git commit -m "<clear change summary>"
   ```

6. Merge into `main` only after the updated system works as expected:

   ```bash
   git checkout main
   git merge <work-branch-name>
   git push
   ```

7. If the branch fails or becomes messy, discard it instead of damaging `main`:

   ```bash
   git checkout main
   git branch -D <work-branch-name>
   ```

Recommended branch names:

- `dev`
- `feature-<short-topic>`
- `fix-<short-topic>`
- `experiment-<short-topic>`

Use `main` as the latest known-good version.
