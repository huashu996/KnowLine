import type {KB,Resource,Graph} from './types';
export type Category=string;
export type KnowledgeItem={id:string;title:string;type:string;category:Category;summary:string;tags:string[];source:any[];layer?:string;status?:string};
export type KnowledgeEdge={id:string;source:string;target:string;relation:string;weight:number};
export type KnowledgeCluster={id:string;name:string;english:string;color:string;x:number;y:number;angle:number;nodeId:string|null;children:number};
export type KnowledgeData={nodes:KnowledgeItem[];edges:KnowledgeEdge[];clusters:KnowledgeCluster[]};
const palette=['#c4bce2','#afe0c8','#ccc5e3','#e4cf9a','#b8d2dd'];
// First-level entries come from the selected knowledge base's configured layers
// and its graph roots. Claim types never become invented top-level categories.
export function knowledgeClusters(kb:KB,graph:Graph):KnowledgeCluster[]{
 const roots=graph.nodes.filter(n=>n.kind==='knowledge_layer');
 const layers=kb.layers?.length?kb.layers:roots.map(n=>({id:n.id,name:n.label,focus:''}));
 return layers.map((l,i)=>{const root=roots.find(n=>n.label===l.name),angle=layers.length===2?i*180+180:-90+i*360/Math.max(1,layers.length),a=angle*Math.PI/180;
 return {id:l.id,name:l.name,english:'Knowledge layer',color:palette[i%palette.length],x:.5+Math.cos(a)*.36,y:.53+Math.sin(a)*.29,angle,nodeId:root?.id||null,children:root?.children||0};});
}
export function adaptKnowledge(kb:KB,cards:any[],resources:Resource[],graph:Graph):KnowledgeData{
 const clusters=knowledgeClusters(kb,graph);
 const members=resources.filter(r=>kb.resource_ids.includes(r.id)),byResource=new Map(members.map(r=>[r.id,r]));
 const nodes:KnowledgeItem[]=cards.map(c=>({id:'card:'+c.id,title:c.title,type:c.type||c.claim_type||'knowledge_card',category:c.layer_id||'__unassigned__',summary:c.content||'',tags:[...new Set<string>([...(c.terms||[]),...(c.aliases||[]),...(c.tags||[]),...(c.topic?[c.topic]:[])])],source:[...(c.imported_sources||[]),...(c.evidence||[]).map((e:any)=>({...e,title:byResource.get(e.resource_id)?.title||e.resource_id}))],layer:kb.layers?.find(l=>l.id===c.layer_id)?.name,status:c.status}));
 nodes.push(...members.map(r=>({id:r.id,title:r.title,type:r.type,category:'__source__',summary:r.note||r.metadata.abstract||'',tags:r.metadata.tags||[],source:[{resource_id:r.id,version_id:r.version_id,title:r.title}],status:r.metadata.metadata_status})));
 const ids=new Set(nodes.map(n=>n.id)),edges:KnowledgeEdge[]=[],seen=new Set<string>();
 const add=(e:KnowledgeEdge)=>{if(ids.has(e.source)&&ids.has(e.target)&&e.source!==e.target&&!seen.has(e.id)){edges.push(e);seen.add(e.id);}};
 for(const c of cards){for(const linked of c.links||[])add({id:'link:'+c.id+':'+linked,source:'card:'+c.id,target:'card:'+linked,relation:c.relations?.find((r:any)=>r.target===linked)?.relation||'knowledge_link',weight:Number(c.relations?.find((r:any)=>r.target===linked)?.weight)||1});for(const resource of new Set<string>((c.evidence||[]).map((e:any)=>e.resource_id)))add({id:'evidence:'+c.id+':'+resource,source:'card:'+c.id,target:resource,relation:'source_evidence',weight:1});}
 for(const e of graph.relations||[])add({id:e.id,source:e.source_id,target:e.target_id,relation:e.kind||'related',weight:Number(e.weight)||1});
 return {nodes,edges,clusters};
}
export function searchKnowledge(data:KnowledgeData,query:string,category:Category|'all'){
 const words=query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean),primary=new Set(data.nodes.filter(n=>(category==='all'||n.category===category)&&words.every(w=>[n.title,n.summary,...n.tags].join(' ').toLocaleLowerCase().includes(w))).map(n=>n.id));
 const context=new Set(primary);for(const e of data.edges)if(primary.has(e.source)||primary.has(e.target)){context.add(e.source);context.add(e.target);}
 return {primary,context};
}
