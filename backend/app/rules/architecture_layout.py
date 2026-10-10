"""Architecture layout helpers.

Positions are computed on the server so the canvas has a sensible initial
arrangement without shipping a graph-layout library to the browser.  The
algorithm is a deterministic layered (Sugiyama-like) placement:

1. every component is assigned to a layer by its tier,
2. components are ordered inside a layer by a stable type ranking,
3. layers advance on X and nodes are vertically centred around the diagram axis.

Running the same input twice therefore produces byte-identical coordinates,
which keeps snapshots, exports and tests stable.
"""

from __future__ import annotations

from app.schemas.architecture import Component, NodePosition
from app.schemas.common import ComponentTier, LogicalComponentType

NODE_WIDTH = 264
NODE_HEIGHT = 124
GAP_X = 132
GAP_Y = 46
LEFT_PADDING = 48

LAYER_BY_TIER: dict[ComponentTier, int] = {
    ComponentTier.EDGE: 0,
    ComponentTier.PRESENTATION: 1,
    ComponentTier.APPLICATION: 2,
    ComponentTier.INTEGRATION: 3,
    ComponentTier.PROCESSING: 4,
    ComponentTier.DATA: 5,
    ComponentTier.SECURITY: 6,
    ComponentTier.OPERATIONS: 6,
}

_TYPE_RANK: dict[LogicalComponentType, int] = {
    LogicalComponentType.CLIENT_WEB: 0,
    LogicalComponentType.CLIENT_MOBILE: 1,
    LogicalComponentType.DNS: 2,
    LogicalComponentType.CDN: 3,
    LogicalComponentType.LOAD_BALANCER: 0,
    LogicalComponentType.API_GATEWAY: 1,
    LogicalComponentType.WEB_SERVER: 2,
    LogicalComponentType.APP_SERVER: 3,
    LogicalComponentType.CONTAINER_SERVICE: 4,
    LogicalComponentType.FUNCTION: 5,
    LogicalComponentType.VIRTUAL_MACHINE: 6,
    LogicalComponentType.QUEUE: 0,
    LogicalComponentType.PUBSUB: 1,
    LogicalComponentType.SCHEDULER: 2,
    LogicalComponentType.DATA_STREAM: 3,
    LogicalComponentType.AUTH_IDENTITY: 0,
    LogicalComponentType.SECRETS_MANAGER: 1,
    LogicalComponentType.WORKER: 0,
    LogicalComponentType.BATCH_JOB: 1,
    LogicalComponentType.REPORTING: 2,
    LogicalComponentType.ML_INFERENCE: 3,
    LogicalComponentType.NOTIFICATION: 4,
    LogicalComponentType.RELATIONAL_DB: 0,
    LogicalComponentType.DOCUMENT_DB: 1,
    LogicalComponentType.KEY_VALUE_DB: 2,
    LogicalComponentType.CACHE: 3,
    LogicalComponentType.SEARCH_INDEX: 4,
    LogicalComponentType.OBJECT_STORAGE: 5,
    LogicalComponentType.BLOCK_STORAGE: 6,
    LogicalComponentType.TIME_SERIES_DB: 7,
    LogicalComponentType.DATA_WAREHOUSE: 8,
    LogicalComponentType.BACKUP: 9,
    LogicalComponentType.MONITORING: 0,
    LogicalComponentType.LOGGING: 1,
    LogicalComponentType.CI_ARTIFACT_STORE: 2,
}


def layer_for(tier: ComponentTier) -> int:
    return LAYER_BY_TIER[tier]


def rank_for(component_type: LogicalComponentType) -> int:
    return _TYPE_RANK.get(component_type, 99)


def layout_components(components: list[Component]) -> dict[str, NodePosition]:
    """Return deterministic canvas positions for a single architecture view."""
    layers: dict[int, list[Component]] = {}
    for component in components:
        component.layer = layer_for(component.tier)
        layers.setdefault(component.layer, []).append(component)

    tallest = max((len(items) for items in layers.values()), default=1)
    axis = tallest * (NODE_HEIGHT + GAP_Y) / 2

    positions: dict[str, NodePosition] = {}
    for layer_index in sorted(layers):
        items = sorted(layers[layer_index], key=lambda item: (rank_for(item.type), item.id))
        for order, component in enumerate(items):
            component.order = order
            column_x = LEFT_PADDING + layer_index * (NODE_WIDTH + GAP_X)
            block = len(items) * (NODE_HEIGHT + GAP_Y) - GAP_Y
            row_y = axis - block / 2 + order * (NODE_HEIGHT + GAP_Y)
            positions[component.id] = NodePosition(x=float(column_x), y=float(round(row_y, 1)))
    return positions
