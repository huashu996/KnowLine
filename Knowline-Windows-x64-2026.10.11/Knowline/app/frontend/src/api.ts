let token = '';
const reads=new Map<string,Promise<any>>();
export function invalidateReads(){reads.clear();}
export class ApiError extends Error {code:string;params:any; constructor(data:any){super(data.code);this.code=data.code;this.params=data.params;}}
export async function api<T=any>(path:string, body?:any, method?:string):Promise<T>{
  const read=!body&&(!method||method==='GET');
  if(read&&reads.has(path))return reads.get(path)!;
  if(!read)reads.clear();
  const work=request<T>(path,body,method);
  if(read){reads.set(path,work);void work.finally(()=>{if(reads.get(path)===work)reads.delete(path);}).catch(()=>{});}
  return work;
}
async function request<T>(path:string,body?:any,method?:string):Promise<T>{
  if(path==='/jobs'&&body&&!method)body={...body,run_agent:body.run_agent??body.run_codex??true};
  const response = await fetch('/api/v1'+path,{method:method|| (body ? 'POST':'GET'),headers:body ? {'Content-Type':'application/json','X-KW-Token':token}: {},body:body ? JSON.stringify({...body,operation_id:body.operation_id||crypto.randomUUID()}):undefined});
  const data = await response.json();
  if(!response.ok) throw new ApiError(data);
  return data;
}
export async function session(){const data=await api('/session');token=data.token;return data;}
export async function institutionalUpload(file:File){
 if(!file.size||file.size>128*1024*1024)throw new ApiError({code:'pdf_invalid'});
 const response=await fetch('/api/v1/institutional/manual-upload',{method:'POST',headers:{'Content-Type':'application/pdf','X-KW-Token':token},body:file});
 const data=await response.json();if(!response.ok)throw new ApiError(data);return data;
}
export const revision = (r:any) => ({base_revision:r.revision,base_sha256:r.sha256,version_id:r.version_id});
export async function replacePDF(resource:any,file:File){
 if(!file.size)throw new ApiError({code:'file_empty'});
 if(file.size>128*1024*1024)throw new ApiError({code:'upload_too_large'});
 const response=await fetch('/api/v1/resources/'+resource.id+'/replace-pdf',{method:'POST',headers:{'Content-Type':'application/pdf','X-KW-Token':token,'X-KW-Operation':crypto.randomUUID(),'X-KW-Revision':String(resource.revision),'X-KW-Version':resource.version_id,'X-KW-Sha256':resource.sha256},body:file});
 const data=await response.json();if(!response.ok)throw new ApiError(data);return data;
}
export async function upload(file:File,kind='paper',domain=''){
 if(!file.size&&kind!=='code')throw new ApiError({code:'file_empty'});
 if(file.size>128*1024*1024)throw new ApiError({code:'upload_too_large',params:{limit_mb:128}});
 const response=await fetch('/api/v1/imports/upload',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-KW-Token':token,'X-KW-Operation':crypto.randomUUID(),'X-KW-Filename':encodeURIComponent(file.name),'X-KW-Kind':kind,'X-KW-Domain':domain},body:file});
 const data=await response.json();if(!response.ok)throw new ApiError(data);return data;
}
