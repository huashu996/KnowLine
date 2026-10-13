const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

// Render the released component: the API intentionally caps the loaded nodes.
const source = fs.readFileSync(path.join(__dirname, '../dist/assets/Network-BfY-IWZk.js'), 'utf8');
const start = source.indexOf('function ct(');
const end = source.indexOf('export{ct as default}', start);
assert.ok(start >= 0 && end > start);
const jsx = (type, props) => ({type, props});
const context = {
  f: {useState: initial => [initial, () => {}], useRef: current => ({current}),
    useEffect() {}, useLayoutEffect() {}, useMemo: fn => fn()},
  t: {jsx, jsxs: jsx, Fragment: 'fragment'},
  Pe: () => key => key, Se: count => Array.from({length: count}, () => ({x: .5, y: .5})),
  te: ['#c5b8ee'], matchMedia: () => ({matches: false}), tt: 'canvas', kwEmptyCards: [],
};
for (const icon of ['Ze', 'Ae', 'Le', '$e', 'Ie', 'Fe', 'Te', 'Ce', 'Ye', 'Be']) context[icon] = 'icon';
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../dist/assets/knowledge-branches.js'), 'utf8').replace(/^export /gm, ''), context);
vm.runInContext(source.slice(start, end), context);

function find(tree, className) {
  if (!tree || typeof tree !== 'object') return;
  if (tree.props?.className === className) return tree;
  for (const child of [].concat(tree.props?.children || [])) {
    const result = find(child, className);
    if (result) return result;
  }
}
function renderCount(total, loaded, global = false) {
  const focus = total === null ? null : {id: 'layer', label: 'Layer', children: total, origin: 'derived'};
  const graph = {focus, nodes: Array.from({length: loaded}, (_, i) => ({
    id: `card-${i}`, label: `Card ${i}`, kind: 'knowledge_card', evidence: [], children: 0,
  })), relations: [], truncated: loaded === 120};
  const tree = context.ct({graph, trail: focus ? [focus] : [], global, onFocus() {}});
  const caption = find(tree, 'network-context').props.children.find(node => node?.type === 'p');
  return caption.props.children[0];
}
for (const total of [0, 1, 7, 119, 120, 121, 553, 2356, 3063]) {
  assert.equal(renderCount(total, Math.min(total, 120)), total, `True total ${total}`);
}
assert.equal(renderCount(null, 3, true), 3, 'Global graph without focus uses loaded knowledge bases');
assert.equal(renderCount(undefined, 7), 7, 'Older payload without total falls back to loaded nodes');
console.log('Knowledge count UI passed: empty, small, limit boundaries, all 3 live totals, and global/legacy fallback.');
