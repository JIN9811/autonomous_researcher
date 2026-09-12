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
last_verified: 2026-09-13
verified_against: working-tree-2026-09-13
related_docs:
  - docs/knowledge/wiki_memory.md
supersedes: []
-->

# Knowledge Publication Boundary

## Status at a Glance

| At a glance | Details |
|---|---|
| Scope | Public Wiki/code versus private runtime and Knowledge data |
| Local check | Staged Git blobs, not working-copy content |
| CI check | Changed blobs between push/PR revisions |
| Default | Private storage roots and source originals cannot be published |
| Limitation | Pattern checks are not exhaustive privacy detection; review remains required |

AX4LAB Wiki is reviewed system knowledge. User profiles, conversations, private
memory, actual experiment data, source originals and generated indexes stay local.
Do not promote a remembered user statement into a public Wiki page automatically.

Before each commit, run:

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

Use synthetic validation content. Sanitized public evidence requires manual review
even when no pattern matches. Never paste real credentials into a test fixture.
Existing tracked data or history findings require a separate report and explicit
remediation decision; these checks do not delete data or rewrite history.
