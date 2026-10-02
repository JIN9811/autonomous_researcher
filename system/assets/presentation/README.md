# Image Assets

> Historical presentation set, reviewed 2026-09-29. These generated prompts and
> diagrams preserve an earlier Prusa-centric architecture and model labels;
> they are not current runtime instructions or experimental evidence. Current
> diagrams are in the [agent references](../../agents/README.md),
> [bridge references](../../device_bridges/README.md), and
> [presentation source index](../../../docs/assets/presentation/README.md).
> The workflow below reproduces this older set, not the current documentation.

This folder contains PPT-ready academic presentation figure-style vector diagrams generated from `diagram_manifest.json`.

- `prompt/*.prompt.md`: image-generation prompts, one per diagram.
- `svg/*.svg`: generated 16:9 vector diagrams.
- `generate_diagrams.py`: deterministic SVG generator.
- `render_diagrams.py`: renders SVGs to PNG and creates `rendered/contact_sheet.png` for visual QA.
- `rendered/*.png`: optional rendered QA outputs for visual inspection.

Style baseline:

- White background.
- Thin strokes, muted colors, and restrained accents suitable for PhD-level research presentations.
- No decorative grid, wave background, or drop shadows.
- Text is generated at 24px or larger for readability in PPT and printed handouts.

Update workflow:

1. Edit `diagram_manifest.json` and the matching prompt intent if the system changes.
2. Run `python3 image/generate_diagrams.py` from the repository root.
3. Run `image/.render_venv/bin/python image/render_diagrams.py` from the repository root.
4. Inspect `image/rendered/contact_sheet.png` and original-size PNGs for text overlap, text outside cards, or arrow/text collision.
5. Insert the SVG files from `image/svg/` directly into PowerPoint or a paper figure pipeline.
