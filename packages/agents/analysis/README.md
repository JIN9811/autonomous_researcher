# Analysis agent package

Analysis owns experimental-data processing, bounded LLM processing and evidence
review, curves, metrics, the configured objective and Knowledge/BO handoffs.
Numerical values are computed by agent-local code. The package has no device
bridge dependency and does not actuate equipment.

The declarative package retains the existing `analysis.task` and
`analysis.deliver` boundaries and loop-scoped artifact storage.
