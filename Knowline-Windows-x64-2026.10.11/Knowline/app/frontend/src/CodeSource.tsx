import {useMemo} from 'react';

// A bounded display lexer; tokens remain React text. Nothing is evaluated or injected.
function lex(text:string,language:string){
 const python=/python/i.test(language),json=/json/i.test(language);
 const pattern=python?/(#[^\n]*|"""[\s\S]*?(?:"""|$)|'''[\s\S]*?(?:'''|$)|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b(?:def|class|import|from|as|return|if|elif|else|for|while|try|except|finally|with|lambda|yield|async|await|in|is|not|and|or|True|False|None|pass|raise)\b|\b\d+(?:\.\d+)?\b)/g:
 /(\/\*[\s\S]*?(?:\*\/|$)|\/\/[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\b(?:const|let|var|function|class|return|if|else|for|while|try|catch|finally|import|export|from|new|public|private|protected|static|void|int|float|double|bool|auto|struct|namespace|using|include|template|typename|async|await|throw|switch|case|break|true|false|null|undefined)\b|\b\d+(?:\.\d+)?\b)/g;
 const lines:{text:string;kind:string}[][]=[[]];let start=0;
 function append(value:string,kind:string){value.split('\n').forEach((part,i)=>{if(i)lines.push([]);if(part)lines[lines.length-1].push({text:part,kind});});}
 for(const match of text.matchAll(pattern)){append(text.slice(start,match.index),'');const value=match[0],kind=value.startsWith('//')||value.startsWith('/*')||python&&value.startsWith('#')?'comment':/^["'`]/.test(value)?'string':/^\d/.test(value)?'number':json?'literal':'keyword';append(value,kind);start=match.index!+value.length;}
 append(text.slice(start),'');return lines;
}
export type CodeMark={id:string;data:{line_start:number;line_end:number;column_start:number;column_end:number;color:number[];comment:string;kind:string}};
export default function CodeSource({text,language,line,selection,annotations=[],onSelectLine,onAnnotation}:{text:string;language:string;line?:number;selection?:{line_start:number;line_end:number};annotations?:CodeMark[];onSelectLine?:(line:number,extend:boolean)=>void;onAnnotation?:(id:string)=>void}){
 const lines=useMemo(()=>lex(text,language),[text,language]);
 return <div className="source-code">{lines.map((parts,i)=>{const marks=annotations.filter(a=>a.data.line_start<=i+1&&a.data.line_end>=i+1);let offset=0;
  return <div key={i} id={'code-line-'+(i+1)} data-line={i+1} className={'code-line '+(line===i+1?'cited ':'')+(selection&&i+1>=selection.line_start&&i+1<=selection.line_end?'code-selected':'')}>
   <button className="line-number" aria-label={'选择代码行 '+(i+1)} onClick={e=>onSelectLine?.(i+1,e.shiftKey)}>{i+1}</button>
   <code>{parts.length?parts.map((part,n)=>{const start=offset;offset+=part.text.length;const ranges=marks.map(a=>({a,start:a.data.line_start===i+1?a.data.column_start:0,end:a.data.line_end===i+1?a.data.column_end:offset}));
    const cuts=[...new Set([start,offset,...ranges.flatMap(r=>[r.start,r.end]).filter(x=>x>start&&x<offset)])].sort((a,b)=>a-b);
    return <span key={n} className={'syntax-'+part.kind}>{cuts.slice(0,-1).map((x,k)=>{const hit=[...ranges].reverse().find(r=>r.start<=x&&r.end>x)?.a;return hit?<mark key={k} data-annotation-id={hit.id} className={'code-mark '+hit.data.kind} style={{background:`rgba(${hit.data.color.map(c=>Math.round(c*255)).join(',')},.32)`}} title={hit.data.comment||'高亮'} onClick={()=>onAnnotation?.(hit.id)}>{part.text.slice(x-start,cuts[k+1]-start)}</mark>:<span key={k}>{part.text.slice(x-start,cuts[k+1]-start)}</span>;})}</span>;
   }):' '}</code>
   {marks.length>0&&<button className="code-annotation-indicator" aria-label={'查看第 '+(i+1)+' 行批注'} onClick={()=>onAnnotation?.(marks[0].id)}>●</button>}
  </div>;
 })}</div>;
}
