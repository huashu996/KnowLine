import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import type {CSSProperties} from 'react';
import {BookOpen,Boxes,ChevronRight,Code2,Database,Globe2,LayoutGrid,Lightbulb,Network,PanelLeft,Plus,Settings,Tag,Terminal,X} from 'lucide-react';
import {useT} from './i18n';
import type {Group,Resource} from './types';
import './navigation.css';

type Section='resources'|'domains'|'knowledge'|'discovery'|'proposal'|'tasks';
type Props={route:string;filter:string;locale:string;workspaceName:string;resources:Resource[];groups:Group[];knowledgeCount:number;jobCount:number;onNavigate:(route:string,type?:string)=>void;onModal:(kind:string)=>void;onRename:()=>void};
const sectionFor=(route:string):Section|null=>route.startsWith('group:')?'domains':route==='kb'?'knowledge':route==='discover'?'discovery':route==='proposal'?'proposal':route==='jobs'?'tasks':['library','papers','code'].includes(route)?'resources':null;

export default function DashboardNavigation(p:Props){
 const t=useT(),currentSection=sectionFor(p.route);
 const [expanded,setExpanded]=useState<Section|null>(currentSection||'resources');
 const [domainExpanded,setDomainExpanded]=useState<string>();
 const [mobileOpen,setMobileOpen]=useState(false);
 const [collapsed,setCollapsed]=useState(()=>localStorage.getItem('kw-nav-collapsed')==='1');
 const [narrow,setNarrow]=useState(()=>window.matchMedia('(max-width:700px)').matches);
 const content=useRef<HTMLDivElement>(null),dock=useRef<HTMLElement>(null);
 const [highlight,setHighlight]=useState<{x:number;y:number;width:number;height:number}>();
 const [pointer,setPointer]=useState<number>(),[focusIndex,setFocusIndex]=useState<number>();
 useEffect(()=>{setExpanded(sectionFor(p.route));if(p.route.startsWith('group:'))setDomainExpanded(p.route.slice(6));},[p.route]);
 useEffect(()=>{document.documentElement.classList.toggle('nav-collapsed',collapsed);localStorage.setItem('kw-nav-collapsed',collapsed?'1':'0');return()=>document.documentElement.classList.remove('nav-collapsed');},[collapsed]);
 useEffect(()=>{const media=window.matchMedia('(max-width:700px)');const update=()=>{setNarrow(media.matches);if(!media.matches)setMobileOpen(false);};media.addEventListener('change',update);return()=>media.removeEventListener('change',update);},[]);
 useEffect(()=>{if(mobileOpen&&narrow)content.current?.querySelector<HTMLButtonElement>('.nav-section-toggle')?.focus({preventScroll:true});},[mobileOpen,narrow]);
 useEffect(()=>{if(!mobileOpen)return;const close=(e:KeyboardEvent)=>{if(e.key==='Escape'){setMobileOpen(false);dock.current?.querySelector<HTMLButtonElement>('.dock-menu')?.focus();}};window.addEventListener('keydown',close);return()=>window.removeEventListener('keydown',close);},[mobileOpen]);
 useLayoutEffect(()=>{
  const node=content.current;if(!node)return;
  const measure=()=>{
   const active=[...node.querySelectorAll<HTMLElement>('[data-nav-current="true"]')].find(el=>el.getBoundingClientRect().height>0&&el.closest('.nav-submenu')?.classList.contains('is-open'))||node.querySelector<HTMLElement>('.nav-section[data-current="true"] .nav-section-toggle');
   if(!active){setHighlight(undefined);return;}
   const a=active.getBoundingClientRect(),b=node.getBoundingClientRect();
   setHighlight({x:a.left-b.left,y:a.top-b.top,width:a.width,height:a.height});
  };
  measure();const observer=new ResizeObserver(measure);observer.observe(node);
  window.addEventListener('resize',measure);return()=>{observer.disconnect();window.removeEventListener('resize',measure);};
 },[p.route,p.filter,expanded,domainExpanded,p.groups,p.locale,mobileOpen]);
 function go(route:string,type?:string){p.onNavigate(route,type);setMobileOpen(false);}
 const item=(id:string,label:string,icon:React.ReactNode,active:boolean,action:()=>void,count?:number,index=0)=><button key={id} className="nav-child" data-nav-current={active} aria-current={active?'page':undefined} onClick={action} style={{'--item-index':index} as CSSProperties}>{icon}<span>{label}</span>{count!=null&&<small>{count}</small>}</button>;
 const section=(id:Section,label:string,icon:React.ReactNode,children:React.ReactNode,extra?:React.ReactNode,directRoute?:string)=><section className="nav-section" key={id} data-section={id} data-current={currentSection===id}>
  <div className="nav-section-heading"><button className="nav-section-toggle" aria-expanded={directRoute?undefined:expanded===id} aria-current={directRoute&&currentSection===id?'page':undefined} aria-controls={directRoute?undefined:'nav-'+id} onClick={()=>directRoute?go(directRoute):setExpanded(expanded===id?null:id)}>{icon}<span className="nav-caption">{label}</span>{!directRoute&&<ChevronRight className="nav-chevron" size={15}/>}</button>{extra}</div>
  {!directRoute&&<div id={'nav-'+id} className={'nav-submenu '+(expanded===id?'is-open':'')} inert={expanded!==id}><div className="nav-submenu-inner"><div className="nav-submenu-items">{children}</div></div></div>}
 </section>;
 const dockItems=[
  {id:'resources',label:t('resources'),icon:<LayoutGrid/>,active:currentSection==='resources',action:()=>{setExpanded('resources');go('library');}},
  {id:'domains',label:t('groups'),icon:<Tag/>,active:currentSection==='domains',action:()=>{setExpanded('domains');if(narrow)setMobileOpen(true);}},
  {id:'knowledge',label:t('knowledge'),icon:<Network/>,active:currentSection==='knowledge',action:()=>{setExpanded('knowledge');go('kb');}},
  {id:'discovery',label:t('discovery'),icon:<Globe2/>,active:currentSection==='discovery',action:()=>{setExpanded('discovery');go('discover');}},
  {id:'proposal',label:p.locale==='zh'?'方案':'Proposal',icon:<Lightbulb/>,active:currentSection==='proposal',action:()=>{setExpanded('proposal');go('proposal');}},
  {id:'tasks',label:p.locale==='zh'?'智能体任务':'Agent tasks',icon:<Terminal/>,active:currentSection==='tasks',action:()=>{setExpanded('tasks');go('jobs');}},
  {id:'settings',label:t('settings'),icon:<Settings/>,active:p.route==='settings',action:()=>go('settings')},
 ];
 const dockScales=dockItems.map((_,i)=>{const el=dock.current?.querySelectorAll<HTMLButtonElement>('.dock-item')[i];const rect=el?.getBoundingClientRect();const distance=pointer!=null&&rect?Math.abs(pointer-(rect.left+rect.width/2)):focusIndex!=null?Math.abs(i-focusIndex)*50:1000;return 1+.48*Math.max(0,1-distance/100)**2;});
 return <>
  {mobileOpen&&<button className="nav-mobile-backdrop" aria-label={p.locale==='zh'?'关闭导航':'Close navigation'} onClick={()=>setMobileOpen(false)}/>}
  <aside className={'sidebar dashboard-sidebar '+(mobileOpen?'mobile-open':'')} inert={narrow&&!mobileOpen}>
   <button className="brand" onClick={()=>go('library')}><span className="brand-mark"><img src="/knowline.svg" width={34} height={34} alt=""/></span><div><strong>{t('brand')}</strong></div></button>
   <button className="mobile-nav-close icon-button" aria-label={p.locale==='zh'?'关闭导航':'Close navigation'} onClick={()=>setMobileOpen(false)}><X size={18}/></button>
   <button className="workspace-label" title={p.locale==='zh'?'重命名空间':'Rename workspace'} onClick={p.onRename}><span className="workspace-avatar">{Array.from(p.workspaceName)[0]?.toUpperCase()}</span><span>{p.workspaceName}</span><ChevronRight size={14}/></button>
   <nav className="dashboard-nav" aria-label={p.locale==='zh'?'侧边导航':'Sidebar navigation'}><div className="nav-content" ref={content}>
    <div className={'nav-active-block '+(highlight?'is-positioned':'')} aria-hidden="true" style={highlight?{width:highlight.width,height:highlight.height,transform:`translate(${highlight.x}px,${highlight.y}px)`}:undefined}/>
    {section('resources',t('resources'),<LayoutGrid size={18}/>,<>
     {item('library',t('library'),<LayoutGrid size={16}/>,p.route==='library',()=>go('library'),p.resources.length)}
     {item('papers',t('papers'),<BookOpen size={16}/>,p.route==='papers',()=>go('papers','paper'),p.resources.filter(r=>r.type==='paper').length,1)}
     {item('code',t('code'),<Code2 size={16}/>,p.route==='code',()=>go('code','code'),p.resources.filter(r=>r.type==='code').length,2)}
    </>)}
    {section('domains',t('groups'),<Boxes size={18}/>,p.groups.length?p.groups.map((g,i)=><div className="nav-domain" key={g.id} style={{'--item-index':i} as CSSProperties}>
     <div className="nav-domain-heading">{item(g.id,g.name,<Tag size={15}/>,p.route==='group:'+g.id&&(p.filter==='all'||domainExpanded!==g.id),()=>{setDomainExpanded(g.id);go('group:'+g.id);},g.resource_ids.length,i)}<button className="domain-expand icon-button" aria-label={(p.locale==='zh'?'展开或收起 ':'Expand or collapse ')+g.name} aria-expanded={domainExpanded===g.id} aria-controls={'nav-domain-'+g.id} onClick={()=>setDomainExpanded(domainExpanded===g.id?undefined:g.id)}><ChevronRight size={13}/></button></div>
     <div id={'nav-domain-'+g.id} className={'nav-domain-types '+(domainExpanded===g.id?'is-open':'')} inert={domainExpanded!==g.id}><div>{['paper','code','link'].map((type,index)=>item(g.id+type,t(type==='paper'?'papers':type==='code'?'code':'links'),type==='paper'?<BookOpen size={14}/>:type==='code'?<Code2 size={14}/>:<Globe2 size={14}/>,p.route==='group:'+g.id&&p.filter===type,()=>go('group:'+g.id,type),p.resources.filter(r=>r.type===type&&g.resource_ids.includes(r.id)).length,index))}</div></div>
    </div>):<p className="nav-no-domains">{p.locale==='zh'?'还没有领域':'No domains yet'}</p>,<button className="icon-button nav-add" aria-label={t('newGroup')} onClick={()=>p.onModal('group')}><Plus size={15}/></button>)}
    {section('knowledge',t('knowledge'),<Network size={18}/>,<>
     {item('kb',t('viewKB'),<Network size={16}/>,p.route==='kb',()=>go('kb'),p.knowledgeCount)}
     {item('build',t('buildKB'),<Database size={16}/>,false,()=>p.onModal('build'),undefined,1)}
    </>)}
    {section('discovery',t('discovery'),<Globe2 size={18}/>,null,undefined,'discover')}
    {section('proposal',p.locale==='zh'?'方案':'Proposal',<Lightbulb size={18}/>,null,undefined,'proposal')}
    {section('tasks',p.locale==='zh'?'智能体任务':'Agent tasks',<Terminal size={18}/>,null,undefined,'jobs')}
   </div></nav>
   <div className="sidebar-bottom"><button className="settings-link" onClick={()=>{const url=new URL(location.href);url.searchParams.set('ui',String(Date.now()));location.replace(url.href);}}>{t('refreshInterface')}</button><button className={'settings-link '+(p.route==='settings'?'active':'')} aria-current={p.route==='settings'?'page':undefined} onClick={()=>go('settings')}><Settings size={17}/>{t('settings')}</button></div>
  </aside>
  <button className="sidebar-collapse-handle" aria-label={collapsed?(p.locale==='zh'?'展开侧栏':'Expand sidebar'):(p.locale==='zh'?'收起侧栏':'Collapse sidebar')} aria-expanded={!collapsed} title={collapsed?(p.locale==='zh'?'展开侧栏':'Expand sidebar'):(p.locale==='zh'?'收起侧栏':'Collapse sidebar')} onClick={()=>setCollapsed(!collapsed)}><ChevronRight size={16}/></button>
  <nav className="dashboard-dock" ref={dock} aria-label={p.locale==='zh'?'快捷导航':'Quick navigation'} onPointerMove={e=>{if(e.pointerType==='mouse')setPointer(e.clientX);}} onPointerLeave={()=>setPointer(undefined)}>
   {dockItems.map((item,i)=><button key={item.id} className={'dock-item '+(item.active?'is-current':'')} data-dock={item.id} aria-label={item.label} aria-current={item.active?'page':undefined} onClick={item.action} onFocus={e=>{if(e.currentTarget.matches(':focus-visible'))setFocusIndex(i);}} onBlur={()=>setFocusIndex(undefined)} style={{'--dock-scale':dockScales[i],'--dock-lift':(dockScales[i]-1)*18+'px'} as CSSProperties}><span className="dock-tooltip" aria-hidden="true">{item.label}</span><span className="dock-icon">{item.icon}</span><span className="dock-dot" aria-hidden="true"/></button>)}
   <button className="dock-item dock-menu" aria-label={p.locale==='zh'?'打开导航菜单':'Open navigation menu'} aria-expanded={mobileOpen} onClick={()=>setMobileOpen(!mobileOpen)}><span className="dock-icon"><PanelLeft/></span></button>
  </nav>
 </>;
}
