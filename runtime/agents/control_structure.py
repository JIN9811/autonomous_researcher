"""Code-owned implementation relationships, never an executable route source."""


def implementation_detail(nodes, edges):
    """Build runtime-relative source references, without opening or importing them.

    Source inspection must use resolve_runtime_reference with explicit paths;
    owner documentation instead uses resolve_document_reference. Neither these
    metadata values nor detached package drafts grant execution/open authority.
    """
    return {
        "nodes": [dict(id=id_, label=label, area=area,
                       source=dict(path=path, symbol=symbol))
                  for id_, label, area, path, symbol in nodes],
        "edges": [dict(source=source, target=target, kind=kind, label=label)
                  for source, target, kind, label in edges],
    }
