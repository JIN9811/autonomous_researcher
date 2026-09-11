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
workflow, at 2048 × 1152, high quality, WebP. No experiment images or numerical
results were synthesized for the paper evidence package.

| Asset | Prompt source | Used in |
|---|---|---|
| Structured AI laboratory overview | [Hero prompt](hero-structured-ai.txt) | Root README, Korean overview, paper introduction |
| Ten agent role diagrams | [Batch prompts](image-prompts.jsonl) | [Agent references](../../agents/README.md) |
| Vision capture-first diagram | [Vision prompt](vision-correction.txt) | Vision reference; supersedes its initial batch image |

Final agent assets reside in [agent figures](../../agents/assets/figures/).
The batch's initial low-cost hero is superseded by the structured-AI overview.

## Presentation References

Only presentation patterns were borrowed, not code, figures, or scientific claims:

- [OpenVLA](https://github.com/openvla/openvla): concise identity and direct research/usage navigation.
- [LeRobot](https://github.com/huggingface/lerobot): capability-first introduction and practical documentation entry points.
- [Coscientist](https://github.com/gomesgroup/coscientist): explicit links between paper sections and supporting artifacts.
