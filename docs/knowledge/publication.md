<!-- atr-doc
doc_type: guide
subtype: operations_runbook
status: active
authority: procedural
audience: [operator, developer, maintainer]
scope: [knowledge, publication_boundary, github]
summary: Pre-commit and CI procedures for preventing private Knowledge data from entering public publication.
source_of_truth:
  - scripts/verify_knowledge_publication.py
last_verified: 2026-09-29
verified_against: dd0d772
related_docs:
  - docs/knowledge/wiki_memory.md
supersedes: []
-->

Verification scope: full-document read and static source inspection at `dd0d772`.
Historical provider/test results retain their original scope; this review did not
invoke models, mutate Knowledge stores or operate devices.

# Knowledge Publication Boundary

Before sharing Knowledge-related changes, decide which material may leave the
laboratory. This guide is for the person preparing a public commit, not a step
required to search local knowledge. A passing scanner is one check in that
decision; it is not exhaustive privacy detection.

AX4LAB Wiki is reviewed system knowledge. User profiles, conversations, private
memory, actual experiment data, source originals and generated indexes stay local.
Do not promote a remembered user statement into a public Wiki page automatically.

Root `oldversion/` is a private local archive for retired outputs and is blocked
even if force-added to Git. It is distinct from the public, reviewed development
history under `docs/oldversion/`.

## Review the exact content being published

1. Separate reviewed public documentation from private memory, source originals
   and experiment artifacts. Do not force-add private roots.
2. Stage only the intended public files, then inspect the staged diff. The
   index is the publication candidate, even if the working copy differs.
3. Run the check below against that staged candidate.
4. Resolve every reported failure and review the staged diff again. Exit 0
   confirms only the configured checks; a human must still review sanitization.
   Do not rely on CI as the first disclosure check.

From the repository root:

```bash
python scripts/verify_knowledge_publication.py
```

The check reads staged blobs. Cleaning a working file after staging it does not
remove sensitive content from the index. Failure reports identify the file index
in `git diff --cached --name-only` order and a reason, never matched content or
potentially identifying filenames. Exit 0 means the configured checks passed;
exit 1 blocks publication, and exit 2 means the inspection itself failed.
An empty staging area checks zero files and is not evidence about untracked data.

The GitHub workflow repeats the check on changed committed blobs. It detects
problems after upload; it cannot undo a disclosure. No local Git hook is installed
automatically. Run the local check and review the staged diff before committing.

Private roots include memory, runs, artifacts, output(s), user_files, logs and
test-results, plus raw inputs under the existing source inbox. Root README and
gitkeep files and the existing top-level memory Python modules remain publishable.
`.gitignore` does not untrack existing files or protect against force-add.

## Approve public evidence and figures

The reviewed Wiki corpus is explicitly listed in `approved_corpora` in
[publication_allowlist.json](publication_allowlist.json). Its ordinary Wiki pages
do not each need a hash. Public evidence does: a file beneath a directory named
`evidence`, or a YAML/JSON/TOML document (or Markdown front matter) whose
`doc_type` is `evidence`, needs an `approved_assets` entry with its
repository-relative path, SHA-256, and a non-sensitive review description. This
requirement applies equally to text and binary evidence; a changed hash
invalidates the approval. Ordinary product documents outside those categories do
not need a hash.

Binary figures also need an exact `approved_assets` review. This never permits
private-root files or detected credentials. Files over the guard's size limit
require a smaller public derivative; original experiment files should stay
private. Credential patterns are checked in every readable blob. Personal
filesystem paths are checked in all decodable non-binary public text, including
documentation, configuration, and source files.

## Handle findings without rewriting history

Use synthetic validation content. Sanitized public evidence requires manual review
even when no pattern matches. Never paste real credentials into a test fixture.
Existing tracked data or history findings require a separate report and explicit
remediation decision; these checks do not delete data or rewrite history.
