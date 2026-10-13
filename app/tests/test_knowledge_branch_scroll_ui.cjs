const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const assert = require('node:assert/strict');
const assets = path.join(__dirname, '../dist/assets');
const helper = fs.readFileSync(path.join(assets, 'knowledge-branches.js'), 'utf8').replace(/^export /gm, '');
const bundle = fs.readFileSync(path.join(assets, 'Network-BfY-IWZk.js'), 'utf8');
const component = bundle.slice(bundle.indexOf('function ct('), bundle.indexOf('export{ct as default}'));
const kb = {id: 'kb_test', revision: 2, build_id: 'build', knowledge_state: 'organized',
  resource_ids: [], layers: [{id: 'base', name: '基础知识'}, {id: 'code', name: '代码架构'}]};
const cards = Array.from({length: 3063}, (_, i) => ({id: `card${i}`, node_id: `node${i}`,
  title: `条目 ${i + 1}`, layer_id: 'code', content: `真实内容 ${i + 1}`, evidence: [], status: 'needs_review'}));
cards.push({id: 'other', node_id: 'other-node', title: 'Other layer', layer_id: 'base', evidence: []});
const graph = {kb_id: kb.id, kb_revision: kb.revision, build_id: kb.build_id,
  focus: {id: 'layer-code', kind: 'knowledge_layer', label: '代码架构', children: 3063},
  nodes: cards.slice(0, 120).map(c => ({id: c.node_id, kind: 'knowledge_card', label: c.title,
    parent_id: 'layer-code', children: 0, evidence: [], status: 'needs_review'})),
  relations: [], edges: [], truncated: true};
graph.nodes[0].label = '已确认的节点名称';
const jsx = (type, props) => ({type, props});
const states = [cards, null, {key: 'kb_test:2:build', error: false}, {focus: null, top: 0}];
let cursor = 0;
const context = {
  f: {useState(initial) {const n = cursor++; if (!(n in states)) states[n] = initial;
    return [states[n], value => {states[n] = typeof value === 'function' ? value(states[n]) : value;}];},
    useRef: current => ({current}), useEffect() {}, useLayoutEffect() {}, useMemo: fn => fn()},
  t: {jsx, jsxs: jsx, Fragment: 'fragment'}, kwEmptyCards: [],
  Pe: () => key => ({branches: '分支'}[key] || key),
  Se: count => Array.from({length: count}, () => ({x: .5, y: .5})),
  te: ['#000'], matchMedia: () => ({matches: false}), tt: 'canvas', We: 'detail',
  Oe: (kb, data) => ({nodes: data.map(c => ({id: `card:${c.id}`, title: c.title, summary: c.content})), edges: []}),
};
for (const name of ['Ze', 'Ae', 'Le', '$e', 'Ie', 'Fe', 'Te', 'Ce', 'Ye', 'Be']) context[name] = 'icon';
vm.createContext(context); vm.runInContext(helper + '\n' + component, context);
function all(tree, predicate) {
  if (Array.isArray(tree)) return tree.flatMap(n => all(n, predicate));
  if (!tree || typeof tree !== 'object') return [];
  return [...(predicate(tree) ? [tree] : []), ...[].concat(tree.props?.children || []).flatMap(c => all(c, predicate))];
}
function render(selectedGraph = graph, selectedKb = kb) {
  cursor = 0; return context.ct({knowledgeBase: selectedKb, resources: [], graph: selectedGraph,
    trail: [selectedGraph.focus], onFocus() {}, onEvidence() {}});
}
function rows(tree) {return all(tree, n => n.props?.['data-branch-node-id']);}
function scroll(tree, top) {
  all(tree, n => n.props?.className === 'cluster-cards tree-scroll')[0].props.onScroll({currentTarget: {scrollTop: top}});
  return render();
}
const complete = context.completeKnowledgeBranch(graph, kb, cards);
assert.equal(complete.nodes.length, 3063);
assert.equal(complete.nodes.at(-1).id, 'node3062');
assert.equal(complete.nodes[0].label, '已确认的节点名称');
assert.equal(complete.truncated, false);
assert.strictEqual(context.completeKnowledgeBranch(graph, {...kb, id: 'another'}, cards), graph);
assert.strictEqual(context.completeKnowledgeBranch(graph, {...kb, revision: 3}, cards), graph);
assert.strictEqual(context.completeKnowledgeBranch(graph, kb, cards.slice(0, 200)), graph);
assert.strictEqual(context.completeKnowledgeBranch({...graph, focus: {...graph.focus, kind: 'resource'}}, kb, cards).nodes, graph.nodes);
let tree = render();
assert.equal(tree.props['data-branch-total'], 3063);
assert.ok(rows(tree).length < 25, 'Bound the rendered DOM without limiting available branches');
assert.equal(rows(tree)[0].props['data-branch-position'], 1);
assert.equal(all(tree, n => n.props?.children === 'more').length, 0, 'No hidden groups of 16');
tree = scroll(tree, 56 * 180);
assert.ok(rows(tree).every(n => n.props['data-branch-position'] > 120), 'Scrolling reaches beyond the graph preview');
tree = scroll(tree, 3063 * 56);
assert.equal(rows(tree).at(-1).props['data-branch-node-id'], 'node3062');
assert.equal(rows(tree).at(-1).props['data-branch-position'], 3063);
rows(tree).at(-1).props.onClick(); tree = render();
assert.equal(all(tree, n => n.type === 'detail')[0].props.node.summary, '真实内容 3063');
const changedFocus = {...graph, focus: {...graph.focus, id: 'new-focus'}};
assert.equal(rows(render(changedFocus))[0].props['data-branch-position'], 1, 'Changing focus resets the visible range');
states[2] = {key: 'old-revision', error: false};
assert.equal(render().props['data-branch-total'], 120, 'Ignore stale card responses');
const crossLayer = [{id: 'shared', node_id: 'shared-code', node_ids: ['shared-base', 'shared-code'],
  layer_id: 'code', layer_ids: ['base', 'code'], title: 'Shared', evidence: []}];
const multiGraph = {...graph, focus: {...graph.focus, children: 1}, nodes: [{id: 'shared-base'}]};
assert.equal(context.completeKnowledgeBranch(multiGraph, kb, crossLayer).nodes[0].id, 'shared-base');
for (const count of [0, 1, 16, 120, 553, 2356, 3063]) {
  const window = context.knowledgeBranchWindow(count, count * 56, 440);
  assert.equal(window.last, count); assert.equal(window.end, count);
  assert.ok(window.end - window.start <= 17);
}
console.log('Full branch scrolling passed: 3063 cards, beyond 120, last card details, bounded rendering, layer/revision isolation, preserved labels, and focus reset.');
