import type {Category,KnowledgeData} from './nebulaData';
// Main count is the actual next-level graph children, not a copied dashboard metric.
export function referenceSummary(data:KnowledgeData,id:Category){const items=data.nodes.filter(n=>n.category===id),cluster=data.clusters.find(c=>c.id===id);return {count:cluster?.children||0,sub:[items.length,'知识条目','cards'],tagged:new Set(items.flatMap(n=>n.source.map(e=>e.document_id||e.resource_id).filter(Boolean))).size};}
