# Evolution Safety Policy

1. Evolution must not directly edit production files.
2. Live hardware control must never use an unapproved evolved variant.
3. Code evolution must produce diff/PR only.
4. All variants must be immutable and traceable.
5. Activation requires schema validation, tests, dry-run, Guardian review, and human approval.
6. Risk score must be stored with every candidate.
7. Rollback must be available for every activation.
8. Candidate evaluation must separate training/source traces from validation/test traces when possible.
