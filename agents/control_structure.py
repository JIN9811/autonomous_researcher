"""Code-owned implementation relationships, never an executable route source."""


def implementation_detail(nodes, edges):
    """Build inspectable source references without importing their implementation."""
    return {
        "nodes": [dict(id=id_, label=label, area=area,
                       source=dict(path=path, symbol=symbol))
                  for id_, label, area, path, symbol in nodes],
        "edges": [dict(source=source, target=target, kind=kind, label=label)
                  for source, target, kind, label in edges],
    }
