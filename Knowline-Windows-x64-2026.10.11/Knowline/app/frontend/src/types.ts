export type Resource = {id:string;type:'paper'|'code'|'link';path:string;title:string;sha256:string;size:number;revision:number;version_id:string;state:string;metadata:Record<string,any>;note:string;groups:string[];versions:{id:string;snapshot_path:string;sha256:string;created_at:string}[]};
export type KB = {id:string;name:string;revision:number;member_revision:number;index_state:string;resource_ids:string[];chunk_count:number;build_id:string;layers?:{id:string;name:string;focus:string}[];knowledge_state?:string;card_count?:number;retrieval?:{model_id:string;learned_model:boolean;units:number;dimensions:number};};
export type Group = {id:string;name:string;revision:number;resource_ids:string[]};
export type Node = {id:string;parent_id:string|null;kind:string;label:string;children:number;origin:string;status:string;evidence:any[]};
export type Graph = {focus:Node|null;nodes:Node[];relations:any[];truncated:boolean};
export type Job = {id:string;question?:string;context_path?:string;task:string;status:string;revision:number;context:any;result:any;created_at:string;draft_artifacts?:{path:string;sha256:string;bytes:number;validation_status:'not_passed';is_draft:true}[]};
