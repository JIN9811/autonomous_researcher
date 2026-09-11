<!-- atr-doc
doc_type: index
subtype: index
status: active
authority: navigation
audience: [researcher, developer]
scope: [documentation_figures]
summary: Sources and generation settings for conceptual presentation images.
related_docs: [README.md, docs/agents/README.md]
supersedes: []
-->

# Presentation Image Sources

The representative images are conceptual architecture overviews. Exact runtime
flows remain in the editable SVG/DOT figures in each agent reference.

Generated with **GPT Image 2**, through the imagegen skill's bundled CLI/API
workflow, at 2048 × 1152 unless noted below, high quality, WebP. No experiment images or numerical
results were synthesized for the paper evidence package.

| Asset | Prompt source | Used in |
|---|---|---|
| Existing-laboratory transformation | [Transformation prompt](laboratory-transformation.txt) | Root README below the logo; 1920 × 960, high quality, WebP |
| Framework overview, agent architecture, integration architecture | [Three-figure prompts](architecture-figures.jsonl) | Root README System Architecture; three independent 1920 × 960 figures, high quality, WebP |
| Previous combined architecture (superseded) | [Initial prompt](orchestration-plan-architecture.txt) · [Graph refinement](orchestration-plan-architecture-revision.txt) · [Label correction](orchestration-plan-architecture-label-fix.txt) | Retained source history; no longer embedded in the root README |
| Structured AI laboratory overview | [Hero prompt](hero-structured-ai.txt) | Korean overview, paper introduction; replaced by the transformation figure in the root README |
| Ten agent role diagrams | [Batch prompts](image-prompts.jsonl) | [Agent references](../../agents/README.md) |
| Vision capture-first diagram | [Vision prompt](vision-correction.txt) | Vision reference; supersedes its initial batch image |

Final agent assets reside in [agent figures](../../agents/assets/figures/).
The batch's initial low-cost hero is superseded by the structured-AI overview.

The root transformation figure adapts the conceptual shift in the author's
2026-09-04 presentation: transform an existing laboratory instead of building
a new automated facility. Matching equipment silhouettes emphasize reuse;
the orchestration graph and robot illustrate the added capabilities, not a
fixed execution sequence or measured deployment outcome.

## Presentation References

Only presentation patterns were borrowed, not code, figures, or scientific claims:

- [OpenVLA](https://github.com/openvla/openvla): concise identity and direct research/usage navigation.
- [LeRobot](https://github.com/huggingface/lerobot): capability-first introduction and practical documentation entry points.
- [Coscientist](https://github.com/gomesgroup/coscientist): explicit links between paper sections and supporting artifacts.
