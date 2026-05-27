# Hermes Self-Evolution Adaptation Notes

Hermes-style self-evolution reads skills/prompts/tools, builds evaluation tasks, uses DSPy + GEPA to mutate text, evaluates variants, and applies the best variants through review.

ATR adaptation uses experimental run traces as the source and targets agent prompts, graph configs, tool descriptions, report templates, policies, and optional code diffs. Activation must respect hardware safety and Guardian gates.

Do not implement uncontrolled self-modifying code.
