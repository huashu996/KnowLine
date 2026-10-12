import type {KnowledgeItem,KnowledgeCluster} from './nebulaData';
export function categoryLayout(narrow=false,clusters:KnowledgeCluster[]=[]){return clusters.map(c=>({...c,...(narrow?{x:c.x,y:c.y}: {})}));}
export function seeded(key:string){let value=2166136261;for(const c of key)value=Math.imul(value^c.charCodeAt(0),16777619);value=Math.imul(value^(value>>>16),2246822507);value=Math.imul(value^(value>>>13),3266489909);return ((value^(value>>>16))>>>0)/4294967296;}
export function itemPosition(n:KnowledgeItem,narrow=false,clusters:KnowledgeCluster[]=[]){const category=clusters.find(c=>c.id===n.category),base=category?category.angle*Math.PI/180:seeded(n.id+':sector')*Math.PI*2,angle=base+(seeded(n.id+':angle')-.5)*1.5,r=.3+seeded(n.id+':r')*.7;return {x:.5+Math.cos(angle)*r*(narrow?.23:.15),y:(narrow?.34:.48)+Math.sin(angle)*r*(narrow?.115:.24),z:(seeded(n.id+':z')-.5)*.8};}
export function visibleItems(items:KnowledgeItem[],primary:Set<string>,context:Set<string>,selected:string|null){
 const candidates=items.filter(n=>context.has(n.id)).sort((a,b)=>Number(b.id===selected)-Number(a.id===selected)||Number(b.category==='__source__')-Number(a.category==='__source__')||a.id.localeCompare(b.id));
 // Reserve part of the display budget for evidence/context even when matching
 // knowledge entries alone exceed the budget. Sources do not become a branch.
 const necessary=candidates.filter(n=>n.id===selected||!primary.has(n.id)||n.category==='__source__').slice(0,24),kept=new Set(necessary.map(n=>n.id));
 return [...necessary,...candidates.filter(n=>!kept.has(n.id))].slice(0,90);
}
