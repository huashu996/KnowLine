import {ApiError} from './api';
export const codeAccept='.c,.cc,.cpp,.cxx,.h,.hh,.hpp,.hxx,.py,.pyi,.js,.jsx,.mjs,.cjs,.ts,.tsx,.java,.kt,.kts,.cs,.go,.rs,.rb,.php,.swift,.m,.mm,.scala,.sc,.vue,.svelte,.html,.htm,.css,.scss,.sass,.less,.sql,.sh,.bash,.zsh,.ps1,.bat,.cmd,.r,.jl,.lua,.pl,.pm,.f,.f90,.f95,.cu,.cuh,.v,.sv,.vhd,.vhdl,.proto,.cmake,.json,.yaml,.yml,.toml,.xml,.ini,.cfg,.conf,.md,.rst,.txt,.gradle,.properties,.tex';
const extensions=new Set(codeAccept.split(',')),names=new Set(['cmakelists.txt','makefile','dockerfile','containerfile','license','readme','.gitignore','.gitattributes','.editorconfig']);
const ignored=new Set(['.git','.svn','.hg','node_modules','venv','.venv','__pycache__','.idea','.vscode','.codex','.agents','dist','build','.knowledge','.claude']);
export function codePath(path:string){const parts=path.split('/'),base=parts[parts.length-1].toLowerCase();return !parts.some(p=>ignored.has(p))&&!base.startsWith('.env')&&!['id_rsa','id_ed25519','credentials','secrets.json','agents.md','claude.md','gemini.md','skill.md'].includes(base)&&(names.has(base)||extensions.has(base.slice(base.lastIndexOf('.'))));}
const table=Array.from({length:256},(_,i)=>{let c=i;for(let j=0;j<8;j++)c=c&1?0xedb88320^(c>>>1):c>>>1;return c>>>0;});
function crc(data:Uint8Array){let c=0xffffffff;for(const n of data)c=table[(c^n)&255]^(c>>>8);return (c^0xffffffff)>>>0;}
// Stored ZIP transport preserves paths without server filesystem access.
export async function projectArchive(files:File[]){
 const selected=files.filter(f=>codePath(f.webkitRelativePath||f.name));
 if(!selected.length)throw new ApiError({code:'code_project_empty'});
 if(selected.length>10000||selected.some(f=>f.size>16*1024*1024)||selected.reduce((n,f)=>n+f.size,0)>127*1024*1024)throw new ApiError({code:'code_import_limit'});
 const root=files[0].webkitRelativePath.split('/')[0]||'代码项目',parts:BlobPart[]=[],central:Uint8Array<ArrayBuffer>[]=[];let offset=0,total=0;
 for(const file of selected){
  const name=new TextEncoder().encode(file.webkitRelativePath||file.name),data=new Uint8Array(await file.arrayBuffer()),sum=crc(data);
  const header=new Uint8Array(30+name.length),view=new DataView(header.buffer);view.setUint32(0,0x04034b50,true);view.setUint16(4,20,true);view.setUint16(6,0x800,true);view.setUint16(12,33,true);view.setUint32(14,sum,true);view.setUint32(18,data.length,true);view.setUint32(22,data.length,true);view.setUint16(26,name.length,true);header.set(name,30);
  const entry=new Uint8Array(46+name.length),v=new DataView(entry.buffer);v.setUint32(0,0x02014b50,true);v.setUint16(4,20,true);v.setUint16(6,20,true);v.setUint16(8,0x800,true);v.setUint16(14,33,true);v.setUint32(16,sum,true);v.setUint32(20,data.length,true);v.setUint32(24,data.length,true);v.setUint16(28,name.length,true);v.setUint32(42,offset,true);entry.set(name,46);
  parts.push(header,file);central.push(entry);offset+=header.length+data.length;total+=entry.length;
 }
 const end=new Uint8Array(22),v=new DataView(end.buffer);v.setUint32(0,0x06054b50,true);v.setUint16(8,central.length,true);v.setUint16(10,central.length,true);v.setUint32(12,total,true);v.setUint32(16,offset,true);
 const archive=new File([...parts,...central,end],root+'.zip',{type:'application/zip'});if(archive.size>128*1024*1024)throw new ApiError({code:'code_import_limit'});
 return {file:archive,skipped:files.length-selected.length};
}
