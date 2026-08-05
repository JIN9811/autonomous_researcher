# Windows Bridge Full Device Style Design

## Goal

Make the complete standalone Windows PyAutoGUI bridge visually consistent with ATR Device Bridge pages and eliminate clipped operational text without changing bridge behavior, element IDs, or API contracts.

## Visual Direction

- Use the shared Device Bridge language: pale blue-gray page surface, white cards, cobalt-blue headings and primary actions, restrained borders, and compact status treatments.
- Keep the Windows package self-contained. Do not import `/static/styles.css` or require the Linux ATR server.
- Preserve the existing header, Essential Console, Program Manager, and Advanced Tools information architecture.
- Apply one Device Bridge shell from the page header through the collapsed and expanded Advanced workspace.

## Layout Rules

- At desktop widths, retain the top Essential Console grid and the Advanced sidebar/workspace split while allowing all columns to shrink safely with `minmax(0, ...)`.
- At narrow widths, stack the sidebar and workspace without sticky height constraints.
- Operational labels, action text, status messages, and guidance must wrap instead of using ellipsis.
- Long paths, commands, and JSON may wrap anywhere or scroll inside their own fields; they must not expand or clip the page.
- Button grids must adapt to available width and must not rely on fixed text width.

## Behavior Constraints

- Preserve all current DOM IDs, JavaScript event bindings, request payloads, and API behavior.
- Preserve the collapsed-by-default Advanced Tools behavior.
- Keep primary and packaged Windows server copies byte-identical.

## Verification

- Open Advanced Tools in an actual browser at 1920x1080 and 1366x768.
- Fail the audit when visible Advanced buttons or operational text have horizontal clipping.
- Capture screenshots with Advanced Tools open and inspect card alignment, wrapping, hierarchy, and overflow.
- Run the Windows bridge helper tests and package smoke tests.
