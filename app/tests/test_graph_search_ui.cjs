const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');

const bundle = path.join(__dirname, '../dist/assets/PaperRelations-3-vizhM_.js');
const source = fs.readFileSync(bundle, 'utf8');
const start = source.indexOf('function ze(');
const end = source.indexOf('export{ze as default}', start);
assert.ok(start >= 0 && end > start, 'Expected the actual released graph component');

function harness(locale = 'zh', options = {}) {
  const states = options.graph ? [options.jobs[0].id, options.graph] : [];
  const requests = [], errors = [];
  let cursor = 0, changed = 0;
  const jsx = (type, props) => ({type, props});
  const context = {
    f: {
      useState(initial) {
        const slot = cursor++;
        if (!(slot in states)) states[slot] = typeof initial === 'function' ? initial() : initial;
        return [states[slot], value => {
          states[slot] = typeof value === 'function' ? value(states[slot]) : value;
        }];
      },
      useRef: initial => ({current: initial}),
      useEffect: () => {},
    },
    e: {jsx, jsxs: jsx, Fragment: 'fragment'},
    fe: () => key => key,
    ae: async (url, body) => {
      requests.push({url, body: body === undefined ? undefined : JSON.parse(JSON.stringify(body))});
      if (url.endsWith('/paper-graph/import-saved')) return {
        imported: 1, missing: 1, fetched_missing:body.fetch_missing,
        rows: [{candidate_id: 'n_saved', resource_id: 'r_saved'}, {candidate_id: 'n_missing',full_text_checked:true}],
      };
      if (url.endsWith('/paper-graph')) return options.graph;
      return {id: 'j_ui_test'};
    },
    ve: 'icon', _e: 'intro', de: status => status, je: 'job',
    we: 'icon', Me: 'icon', ke: 'icon', Ne: 'icon', Ce: 'icon',
    pe: authors => authors.join('; '), qe: 'graph',
  };
  vm.createContext(context);
  vm.runInContext(source.slice(start, end), context);
  vm.runInContext(source.slice(source.indexOf('function kwFullTextState(')), context);
  return {
    requests, errors,
    get changed() {return changed;},
    render() {
      cursor = 0;
      return context.ze({
        jobs: options.jobs || [], groups: [], locale,
        onChange: async () => {changed++;},
        onError: error => {errors.push(error);},
      });
    },
  };
}

function all(tree, predicate) {
  const found = [];
  function visit(value) {
    if (Array.isArray(value)) {value.forEach(visit); return;}
    if (!value || typeof value !== 'object') return;
    if (predicate(value)) found.push(value);
    if (value.props) visit(value.props.children);
  }
  visit(tree);
  return found;
}

function originField(tree, locale = 'zh') {
  const label = all(tree, node => node.type === 'label' &&
    node.props.children?.[0] === (locale === 'zh' ? '起点论文标题' : 'Origin paper title'));
  assert.equal(label.length, 1);
  return all(label[0], node => node.type === 'input')[0];
}

function instructionsField(tree) {
  const fields = all(tree, node => node.type === 'textarea');
  assert.equal(fields.length, 1, 'Optional narrative input appears exactly once');
  return fields[0];
}

function createButton(tree, locale = 'zh') {
  const buttons = all(tree, node => node.type === 'button' && node.props.children ===
    (locale === 'zh' ? '创建关系图任务' : 'Create graph task'));
  assert.equal(buttons.length, 1);
  return buttons[0];
}

const flush = async () => {
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
};

async function verifyForms() {
  const h = harness();
  let tree = h.render();
  const notes = instructionsField(tree);
  assert.equal(notes.props.maxLength, 2000);
  assert.equal(notes.props.rows, 3);
  assert.equal(notes.props['aria-label'], '星图搜索侧重点');
  assert.match(notes.props.placeholder, /TRO、RA-L/);
  assert.equal(createButton(tree).props.disabled, true);
  notes.props.onChange({target: {value: '  以 TRO、RA-L 为主\n关注退化场景与实时性  '}});
  tree = h.render();
  assert.equal(createButton(tree).props.disabled, true, 'Narrative alone does not replace the origin paper');
  const origin = 'KISS-ICP: In Defense of Point-to-Point ICP';
  originField(tree).props.onChange({target: {value: origin}});
  tree = h.render();
  assert.equal(originField(tree).props.value, origin);
  assert.equal(instructionsField(tree).props.value, '  以 TRO、RA-L 为主\n关注退化场景与实时性  ');
  assert.equal(createButton(tree).props.disabled, false);
  createButton(tree).props.onClick();
  await flush();
  assert.deepEqual(h.errors, []);
  assert.equal(h.changed, 1);
  assert.equal(h.requests.length, 1, 'Submit creates one task, not a second PDF-search task');
  const request = h.requests[0];
  assert.equal(request.url, '/jobs');
  assert.equal(request.body.task, 'paper_relationships');
  assert.equal(request.body.query, origin, 'Exact origin title is not contaminated by venue preferences');
  assert.equal(request.body.search_instructions, '以 TRO、RA-L 为主\n关注退化场景与实时性');
  assert.equal(request.body.question, origin + '\n' + request.body.search_instructions);
  assert.equal(request.body.target_count, 20);
  assert.equal(request.body.skill, 'knowline-paper-relations');

  const english = harness('en');
  tree = english.render();
  assert.equal(instructionsField(tree).props['aria-label'], 'Graph search instructions');
  originField(tree, 'en').props.onChange({target: {value: 'KISS-ICP'}});
  instructionsField(tree).props.onChange({target: {value: '  \n  '}});
  tree = english.render();
  const connected = all(tree, node => node.type === 'input' &&
    node.props['aria-label'] === 'Connected Papers graph URL')[0];
  connected.props.onChange({target: {value: ' https://www.connectedpapers.com/main/test/graph '}});
  tree = english.render();
  createButton(tree, 'en').props.onClick();
  await flush();
  assert.deepEqual(english.errors, []);
  assert.equal(english.requests.length, 1);
  assert.equal(english.requests[0].body.query, 'KISS-ICP');
  assert.equal(english.requests[0].body.search_instructions, '');
  assert.equal(english.requests[0].body.question, 'KISS-ICP', 'Empty narrative adds no blank line');
  assert.equal(english.requests[0].body.connected_papers_url, 'https://www.connectedpapers.com/main/test/graph');
}

async function verifyImportSkip() {
  const graph = {
    origin_id: 'n_saved', edges: [],
    full_text_summary: {pdf_saved: 1, pdf_missing: 1, abstracts: 0},
    nodes: [
      {id: 'n_saved', title: 'Saved origin', authors: ['Author One'], year: 2024,
        citation_count: null, cached_resources: [{resource_id: 'r_saved', version_id: 'v_saved'}],
        metadata_source: {url: 'https://doi.org/10.1/saved'}},
      {id: 'n_missing', title: 'Missing related paper', authors: ['Author Two'], year: 2025,
        citation_count: null, full_text_reason: 'public_repository_no_identity_match; github_no_verified_pdf',
        metadata_source: {url: 'https://doi.org/10.1/missing'}},
    ],
  };
  const jobs = [{id: 'j_existing_graph', task: 'paper_relationships', revision: 5, status: 'partial',
    context: {scope: {}, literature_search: {query: 'Saved origin'}}}];
  for (const locale of ['zh', 'en']) {
    const h = harness(locale, {graph, jobs});
    let tree = h.render();
    const fields = all(tree, node => node.type === 'input' && node.props.type === 'checkbox');
    assert.equal(fields.length, 2);
    fields.forEach(field => field.props.onChange());
    tree = h.render();
    assert.equal(all(tree, node => node.type === 'input' && node.props.type === 'checkbox' && node.props.checked).length, 2);
    const find = all(tree, node => node.type === 'button' && Array.isArray(node.props.children) && node.props.children.includes(
      locale === 'zh' ? '导入选中论文' : 'Import selected papers'));
    assert.equal(find.length, 1);
    find[0].props.onClick();
    await flush();
    assert.deepEqual(h.errors, []);
    const imports = h.requests.filter(request => request.url.endsWith('/paper-graph/import-saved'));
    assert.equal(imports.length, 1, 'Only one bounded import/fetch request');
    assert.deepEqual(imports[0].body, {
      base_revision: 5, candidate_ids: ['n_saved', 'n_missing'], destination: 'library', fetch_missing: true,
    });
    assert.equal(h.requests.filter(request => request.url.endsWith('/paper-graph')).length, 1,
      'One read-only graph refresh after acquisition');
    assert.equal(h.requests.filter(request => request.url === '/jobs').length, 0, 'No new search task');
    assert.equal(h.changed, 1);
    tree = h.render();
    assert.equal(all(tree, node => node.type === 'input' && node.props.type === 'checkbox' && node.props.checked).length, 0,
      'Processed missing items are not automatically kept selected for repeated fetching');
    assert.equal(all(tree, node => node.type === 'button' && node.props.children ===
      (locale === 'zh' ? '查找选中论文的 PDF' : 'Find selected PDFs')).length, 0);
    const status = all(tree, node => node.type === 'p' && node.props.className === 'paper-import-status');
    assert.equal(status.length, 1);
    assert.match(status[0].props.children, locale === 'zh' ? /1 篇查后未取得 PDF/ : /1 checked but no PDF acquired/);
    assert.match(status[0].props.children, locale === 'zh' ? /原因见论文详情.*主动重试/ : /See paper details.*retry manually/);
    assert.doesNotMatch(status[0].props.children, /补齐|继续查找|PDFs unavailable/);
    await flush();
    assert.equal(h.requests.length, 2, 'Settling state does not automatically retry');
  }
}

function verifySkipLabels() {
  const context = {e: {jsx: (type, props) => ({type, props}), jsxs: (type, props) => ({type, props})}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function kwFullTextState(')), context);
  for (const reason of ['public_index_unavailable; http_429', 'github_search_unavailable', 'locator_timeout']) {
    const node = {full_text_reason: reason};
    assert.equal(context.kwFullTextState(node), 'search_incomplete');
    const label = context.kwFullTextLabel(node, true);
    assert.match(label, /查询未完成/);
    assert.doesNotMatch(label, /主要[公公開]*源未定位全文|已检查来源暂未找到全文/);
    assert.match(label, /不代表/);
  }
  const checked = {full_text_reason: 'public_repository_no_identity_match; github_no_verified_pdf',full_text_checked:true};
  assert.equal(context.kwFullTextState(checked), 'not_found');
  assert.match(context.kwFullTextLabel(checked, true), /查后未取得 PDF/);
  assert.doesNotMatch(context.kwFullTextLabel(checked, true), /不存在|永久|无法获取/);
  assert.equal(context.kwFullTextState({...checked, cached_resources: [{resource_id: 'r_verified'}]}), 'acquired');
  assert.equal(context.kwFullTextState({...checked,full_text_checked:false}),'not_checked');
  assert.match(context.kwFullTextLabel({...checked,full_text_checked:undefined},true),/查询状态未记录/);
  assert.match(context.kwImportOutcome({imported:4,missing:8,fetched_missing:false,rows:[]},true),/查询状态未记录/);
  assert.match(context.kwImportOutcome({imported:4,missing:1,fetched_missing:false,rows:[{}]},true),/本轮未查询 PDF/);
  const covered=JSON.stringify(context.kwPdfCoverage({full_text_sources:[
    {provider:'arXiv',status:'unavailable',reason:'network_error'},
    {provider:'GitHub',status:'no_match',request_sent:true},
    {provider:'Semantic Scholar',status:'cooldown',request_sent:false}]},true));
  assert.match(covered,/arXiv/);assert.match(covered,/GitHub/);assert.match(covered,/查询／访问失败/);
  assert.match(covered,/限流冷却/);assert.match(covered,/Sci-Hub.*未接入，未查/);
  assert.equal(context.kwRelationSummary({nodes:[{citation_count:0,references_checked:true},{citation_count:null}],edges:[{kind:'citation'},{kind:'semantic_similarity'}]},true),
    '被引数量已核实 1/2 · 参考列表已核查 1/2 · 已核验引用边 1 条');
  const reference=JSON.stringify(context.kwRelationCoverage({references_checked:true,references_without_doi:5,references_unresolved_count:4,reference_sources:[{provider:'Crossref',status:'checked'},{provider:'Semantic Scholar',status:'not_checked'}]},true));
  assert.match(reference,/Semantic Scholar.*未查/);assert.match(reference,/尚未解析身份 4 条/);
  assert.match(reference,/不等于遗漏的图内引用边/);
}

function verifyPatchIdempotence() {
  const python = process.env.KNOWLINE_TEST_PYTHON ||
    'python';
  const script = path.resolve(__dirname, '../scripts/update_graph_search_options_ui.py');
  // Import the patch function and verify against strings only: this test never
  // edits the real bundle, even if another agent is preparing a runtime update.
  const program = [
    'import importlib.util, pathlib, sys',
    'spec = importlib.util.spec_from_file_location("graph_patch", sys.argv[1])',
    'm = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)',
    'source = pathlib.Path(sys.argv[2]).read_text("utf-8")',
    'assert m.patch(source) == source',
    'legacy = source.replace(m.STATE_NEW, m.STATE_OLD, 1).replace(m.PAYLOAD_NEW, m.PAYLOAD_OLD, 1).replace(m.FIELD + m.HELP, "", 1)',
    'for old, new in [(m.SELECTION_OLD, m.SELECTION_NEW), (m.IMPORT_ZH_OLD, m.IMPORT_ZH_NEW), (m.IMPORT_EN_OLD, m.IMPORT_EN_NEW), (m.INCOMPLETE_OLD, m.INCOMPLETE_NEW), (m.NOT_FOUND_OLD, m.NOT_FOUND_NEW)]: legacy = legacy.replace(new, old, 1)',
    'assert m.patch(legacy) == source',
    'intermediate = source.replace(m.IMPORT_EN_NEW, m.IMPORT_EN_INTERMEDIATE, 1).replace(m.NOT_FOUND_NEW, m.NOT_FOUND_TYPO, 1)',
    'assert m.patch(intermediate) == source',
    'try: m.patch(legacy.replace(m.STATE_OLD, "unknown-state-anchor", 1))',
    'except ValueError: pass',
    'else: raise AssertionError("Unknown bundle must fail before writing")',
    'print("Idempotent current/legacy patch and fail-fast unknown-bundle checks passed.")',
  ].join('\n');
  const result = spawnSync(python, ['-c', program, script, bundle], {encoding: 'utf8'});
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  process.stdout.write(result.stdout);
}

(async () => {
  await verifyForms();
  await verifyImportSkip();
  verifySkipLabels();
  verifyPatchIdempotence();
  console.log('Graph search UI passed: real component events, separate origin/narrative, bilingual form, bounded import/fetch, cleared selection, honest skip diagnostics.');
})().catch(error => {console.error(error); process.exitCode = 1;});
