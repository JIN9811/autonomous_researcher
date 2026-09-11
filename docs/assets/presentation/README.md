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

The active generated figures use **GPT Image 2.5 Sunburst** through the imagegen
skill's bundled CLI/API workflow: high-quality WebP, normally 1536 × 1024;
the System Contribution strip is 2172 × 724 (3:1), and the Device Bridge overview
is 1983 × 793 (approximately 5:2), both generated with automatic canvas sizing.
No experiment images or numerical results were synthesized for the paper
evidence package.

| Asset | Prompt source | Used in |
|---|---|---|
| Multi-agent laboratory transformation | [Sunburst prompt](laboratory-transformation-sunburst.txt) · [Flat-style refinement](laboratory-transformation-sunburst-refinement.txt) · [Diagonal layout and bullet alignment](laboratory-transformation-sunburst-diagonal.txt) | Root README Graphical Abstract, Korean overview and paper introduction; approved image retained unchanged |
| SDL adoption barriers | [Motivation prompt](motivation-contribution-sunburst.jsonl), entry 1 | Root README Motivation; conceptual barriers, not a quantitative cost comparison |
| Three system contributions | [Horizontal three-module redesign](system-contribution-horizontal.txt) · [Two-line typography refinement](system-contribution-typography.txt) | Root README immediately above the contribution table; three parallel contributions, not sequential runtime stages |
| Framework overview, agent architecture, integration architecture | [Sunburst paper-figure prompts](sunburst-paper-figures.jsonl), entries 1–3 | Root README System Architecture |
| Ten agent role diagrams | [Sunburst paper-figure prompts](sunburst-paper-figures.jsonl), entries 4–13; [Design handoff refinement](sunburst-design-handoff-refinement.txt) | [Agent references](../../agents/README.md); existing image paths retained |
| Device Bridge integration overview | [Device Bridge prompt](device-bridge-overview.txt) · [Shared evidence-return refinement](device-bridge-evidence-refinement.txt) | [Device Bridge index](../../device_bridges/README.md); physical integration approaches with a separate evidence return |

Final agent assets reside in [agent figures](../../agents/assets/figures/).

The motivation/contribution pair adds
[adoption barriers](self-driving-lab-barriers.webp) and
[the AX4LAB approach](ax4lab-transformation-approach.webp). The first isolates
acquisition, integration, and reconfiguration burdens; the second places
hierarchical automation, multi-agent coordination, and VLA-based manipulation
side-by-side as compact box-like modules, without hardware pictograms.
Neither replaces the approved
Graphical Abstract or the three detailed architecture overviews.

## Paper-Figure Style

- Flat technical pictograms on white, consistent navy outlines and cyan connections.
- Short English labels, one sans-serif family, open layouts without enclosing cards.
- Distinct reasoning, procedure, tool and evidence roles; arrows preserve actual ownership.
- Role-specific layouts: peer-agent orchestration, terminal workflow review, and parallel FEM are not forced into one sequential template.

The System Contribution strip intentionally uses three equal outlined modules,
as requested for this figure only. Matching two-line headings, aligned diagram
baselines, and thin cyan accent rules establish its typographic hierarchy.
Other paper figures retain their open layouts.

The prompts were checked against the corresponding agent references. They retain
optimizer authority over coordinates, capture before Vision review, terminated
robot execution before result judgment, and measured handoff independent of FEM.
Guardian's model review remains advisory to policy gates. These are conceptual
responsibility diagrams, not new runtime paths or validation results.

This refresh changes only generated raster figures and their documentation
references. Existing SVG diagrams, measured plots, FEM contours, screenshots,
branding files, and the approved Graphical Abstract are outside its scope.

The root transformation figure adapts the conceptual shift in the author's
2026-09-04 presentation: transform an existing laboratory instead of building
a new automated facility. The AX4LAB wordmark sits above the transformation
arrow; the laboratory, AI processor, and Device Bridge descend in a staggered
layout. Generic equipment categories connect through Device Bridge.
The centered, left-aligned bullet list describes equipment reuse, integration
from low-cost to general-purpose hardware, and multi-agent transformation, not a
fixed execution sequence or measured deployment outcome.

## Superseded Generation Sources

The former tall System Contribution composition is superseded by the horizontal
strip: [initial prompt](motivation-contribution-sunburst.jsonl), entry 2, and
[control-routing refinement](ax4lab-transformation-approach-refinement.txt).

Previous GPT Image 2 prompts and unused images are retained as source history,
not active presentation figures:

- [Original agent batch](image-prompts.jsonl) and [Vision correction](vision-correction.txt).
- [Original architecture figures](architecture-figures.jsonl).
- [Combined architecture](orchestration-plan-architecture.txt), [refinement](orchestration-plan-architecture-revision.txt), and [label correction](orchestration-plan-architecture-label-fix.txt).
- [Structured-AI hero](hero-structured-ai.txt) and [earlier transformation](laboratory-transformation.txt).

## Presentation References

Only presentation patterns were borrowed, not code, figures, or scientific claims:

- [OpenVLA](https://github.com/openvla/openvla): concise identity and direct research/usage navigation.
- [LeRobot](https://github.com/huggingface/lerobot): capability-first introduction and practical documentation entry points.
- [Coscientist](https://github.com/gomesgroup/coscientist): explicit links between paper sections and supporting artifacts.
