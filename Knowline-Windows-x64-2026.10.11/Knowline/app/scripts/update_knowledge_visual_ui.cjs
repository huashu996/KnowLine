// This release ships built assets. Keep module URLs consistent after patching.
const fs = require('node:fs');
const path = require('node:path');
const app = path.resolve(__dirname, '..');
const assets = path.join(app, 'dist/assets');
const network = path.join(assets, 'Network-BfY-IWZk.js');
const oldCount = 'children:[l.nodes.length," ",s(k?"knowledge":"branches")]';
const newCount = 'children:[l.focus?.children??l.nodes.length," ",s(k?"knowledge":"branches")]';
const source = fs.readFileSync(network, 'utf8');
if (source.split(oldCount).length === 2) {
  fs.writeFileSync(network, source.replace(oldCount, newCount));
} else if (source.split(newCount).length !== 2) {
  throw new Error('Unexpected knowledge network count markup');
}
const revision = 'knowledge-visual-v1';
const reference = /(["'])((?:\.\/|\/assets\/|assets\/)[^"'\s?#]+\.(?:js|mjs|css))(?:\?kw_ui=[a-z0-9-]+)?\1/g;
const files = [path.join(app, 'dist/index.html'), ...fs.readdirSync(assets)
  .filter(name => /\.(?:js|mjs)$/.test(name)).map(name => path.join(assets, name))];
let changed = 0;
for (const file of files) {
  const before = fs.readFileSync(file, 'utf8');
  let after = before.replace(reference, (_, quote, url) => `${quote}${url}?kw_ui=${revision}${quote}`);
  if (path.basename(file) === 'index-DDV0cMc3.js') {
    after = after.replace('M.endsWith(".css")', 'M.split("?",1)[0].endsWith(".css")');
  }
  if (path.basename(file) === 'index.html') {
    after = after.replace(/(knowline-design\.css\?v=)[^"']+/, (_, prefix) => `${prefix}20261013-6`);
  }
  if (after !== before) { fs.writeFileSync(file, after); changed++; }
}
console.log(`Knowledge branch total fixed; ${changed} frontend asset references updated.`);
