# BO agent package

The BO agent owns measured-evidence admission, bounded local LLM strategy and
result review, and the next Design request. Existing `learning/` and
`experiments/` services retain LHS, BoTorch, acquisition and candidate
coordinate ownership.

The package has no Device Bridge or direct physical effect. Its declaration
does not execute an optimizer, call a model or alter workspace settings.
