// Apply narrowly to the shipped component; preserve unrelated release changes.
const fs = require('node:fs');
const path = require('node:path');
const file = path.join(__dirname, '../dist/assets/Network-BfY-IWZk.js');
let source = fs.readFileSync(file, 'utf8');
function replace(before, after) {
  if (source.includes(after)) return;
  if (source.split(before).length !== 2) throw new Error('Unexpected branch UI: ' + before.slice(0, 90));
  source = source.replace(before, after);
}
replace('function ct(', 'const kwEmptyCards=[];function ct(');
replace('const[x,C]=f.useState([]),[_,h]=f.useState(null);',
  'const[x,C]=f.useState([]),[_,h]=f.useState(null),[kwCardsState,kwSetCardsState]=f.useState({key:"",error:false}),[kwScroll,kwSetScroll]=f.useState({focus:null,top:0});const kwCardsKey=M?[M.id,M.revision,M.build_id].join(":"):"";');
replace('return M&&_e("/knowledge-bases/"+M.id+"/cards").then(i=>{e&&C(i.cards)}),()=>{e=!1}',
  'return M&&_e("/knowledge-bases/"+M.id+"/cards").then(i=>{if(!e)return;if(!Array.isArray(i.cards)||!i.knowledge_base||[i.knowledge_base.id,i.knowledge_base.revision,i.knowledge_base.build_id].join(":")!==kwCardsKey)throw new Error("Knowledge revision changed");C(i.cards);kwSetCardsState({key:kwCardsKey,error:false})}).catch(()=>{e&&kwSetCardsState({key:kwCardsKey,error:true})}),()=>{e=!1}');
replace('const N=M?Oe(M,x,u,l):null,',
  'const kwCards=kwCardsState.key===kwCardsKey&&!kwCardsState.error?x:kwEmptyCards;l=f.useMemo(()=>completeKnowledgeBranch(l,M,kwCards),[l,M,kwCards]);const N=f.useMemo(()=>M?Oe(M,kwCards,u,l):null,[M,kwCards,u,l]),');
replace('const n=l.nodes.slice(S*Q,S*Q+Q),a=Se(p?0:n.length),c=Math.max(ie,n.length*56),',
  'const kwWindow=knowledgeBranchWindow(l.nodes.length,kwScroll.focus===l.focus?.id?kwScroll.top:0,ie),kwZh=s("branches")==="分支",n=p?l.nodes.slice(kwWindow.start,kwWindow.end):l.nodes.slice(S*Q,S*Q+Q),a=Se(p?0:n.length),c=p?kwWindow.height:Math.max(ie,n.length*56),');
replace('const i=x.find(z=>z.node_id===e.id);', 'const i=kwCards.find(z=>z.node_id===e.id||z.node_ids?.includes(e.id));');
replace('"data-clusters":n.length,"data-layout":', '"data-clusters":n.length,"data-branch-total":l.nodes.length,"data-layout":');
replace('ref:J,className:"cluster-cards"+(p?" tree-scroll":""),',
  'ref:J,className:"cluster-cards"+(p?" tree-scroll":""),tabIndex:p?0:void 0,role:p?"region":void 0,"aria-label":p?(kwZh?"全部知识分支，可滚动浏览":"All knowledge branches, scroll to browse"):void 0,onScroll:p?e=>kwSetScroll({focus:l.focus?.id,top:e.currentTarget.scrollTop}):void 0,');
replace('"data-branch-index":i,className:', '"data-branch-index":i,"data-branch-position":p?kwWindow.start+i+1:S*Q+i+1,className:');
replace('p?(i+.5)*c/n.length+"px":a[i].y*100+"%"', 'p?(kwWindow.start+i+.5)*56+"px":a[i].y*100+"%"');
replace('children:[s(e.kind)," · "]', 'children:[s(e.kind==="knowledge_card"?"knowledgeEntry":e.kind)," · "]');
replace('l.nodes.length>Q&&t.jsxs(t.Fragment,', '!p&&l.nodes.length>Q&&t.jsxs(t.Fragment,');
replace('s("reduceMotion")]}),t.jsx("button",',
  's("reduceMotion")]}),p&&t.jsxs("span",{className:"knowledge-branch-range",role:"status",children:[kwZh?"显示 ":"Showing ",kwWindow.first,"–",kwWindow.last," / ",l.nodes.length,kwZh?" 条":" branches"]}),p&&t.jsx("button",{onClick:()=>J.current?.scrollTo(0,0),children:kwZh?"回到开头":"First branch"}),p&&t.jsx("button",{onClick:()=>J.current?.scrollTo(0,c),children:kwZh?"跳到末尾":"Last branch"}),t.jsx("button",');
replace('l.truncated&&t.jsx("div",{className:"graph-truncated",children:s("truncated")})',
  'l.truncated&&t.jsx("div",{className:"graph-truncated",role:"status",children:kwCardsState.error?(kwZh?"完整分支加载失败，请刷新界面重试。":"Full branch list failed to load. Refresh to retry."):kwCardsState.key!==kwCardsKey?(kwZh?"正在加载全部分支…":"Loading all branches…"):s("truncated")})');
if (!source.includes('import{completeKnowledgeBranch,knowledgeBranchWindow}')) {
  source = 'import{completeKnowledgeBranch,knowledgeBranchWindow}from"./knowledge-branches.js";\n' + source;
}
fs.writeFileSync(file, source);
console.log('Knowledge branches now use the complete card list and a continuous virtual scroll.');
