// The graph endpoint is a bounded preview. Published cards contain the complete
// layer membership and the real persistent node IDs used by the detail view.
export function completeKnowledgeBranch(graph, kb, cards) {
  if (!kb || graph.kb_id !== kb.id || graph.focus?.kind !== 'knowledge_layer' ||
      !cards.length || graph.kb_revision !== kb.revision || graph.build_id !== kb.build_id) return graph;
  const layers = kb.layers || [], byNode = new Map();
  for (const card of cards) {
    const membership = card.layer_ids || [card.layer_id];
    const orderedLayers = layers.filter(layer => membership.includes(layer.id));
    // Authored cards store node_ids in knowledge-layer order; imported and old
    // cards have a single primary node_id. Never invent a structural node ID.
    if (card.node_ids?.length === orderedLayers.length) {
      orderedLayers.forEach((layer, i) => {
        if (card.node_ids[i]) byNode.set(card.node_ids[i], {card, layerId: layer.id});
      });
    } else if (card.node_id) {
      byNode.set(card.node_id, {card, layerId: card.layer_id});
    }
  }
  const layerIds = new Set(graph.nodes.map(node => byNode.get(node.id)?.layerId));
  if (layerIds.size !== 1 || layerIds.has(undefined)) return graph;
  const layerId = [...layerIds][0];
  const existing = new Map(graph.nodes.map(node => [node.id, node]));
  const nodes = [];
  for (const [id, {card, layerId: memberLayer}] of byNode) {
    if (memberLayer !== layerId) continue;
    nodes.push(existing.get(id) || {
      id, kb_id: kb.id, parent_id: graph.focus.id,
      kind: card.figure ? 'figure' : 'knowledge_card', label: card.title,
      origin: 'derived', status: card.status || 'needs_review',
      evidence: card.evidence || [], children: 0,
    });
  }
  // A partial or mismatched card response must never masquerade as the full list.
  if (nodes.length !== graph.focus.children || nodes.length < graph.nodes.length) return graph;
  return {...graph, nodes, truncated: false};
}

export function knowledgeBranchWindow(total, scrollTop, height) {
  const rowHeight = 56, viewport = Math.max(rowHeight, height || 440);
  const top = Math.max(0, Math.min(scrollTop || 0, total * rowHeight - viewport));
  return {
    start: Math.max(0, Math.floor(top / rowHeight) - 4),
    end: Math.min(total, Math.ceil((top + viewport) / rowHeight) + 4),
    first: total ? Math.floor(top / rowHeight) + 1 : 0,
    last: Math.min(total, Math.ceil((top + viewport) / rowHeight)),
    height: Math.max(viewport, total * rowHeight),
  };
}
