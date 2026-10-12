import {lazy,Suspense,type ComponentProps,type ReactNode} from 'react';
import {useT} from './i18n';
const PDF=lazy(()=>import('./Readers').then(module=>({default:module.PDFReader})));
const Nebula=lazy(()=>import('./NebulaKnowledgeNetwork'));
const Graph=lazy(()=>import('./Network'));
const Relations=lazy(()=>import('./PaperRelations'));
const Proposal=lazy(()=>import('./ProposalWorkbench'));
const Cards=lazy(()=>import('./KnowledgeCards'));
const Storage=lazy(()=>import('./StorageSettings'));
const Word=lazy(()=>import('./WordPanel'));
function Boundary({children}:{children:ReactNode}){const t=useT();return <Suspense fallback={<div className="workspace-loading" role="status">{t('checking')}</div>}>{children}</Suspense>;}
export function PDFReader(props:ComponentProps<typeof PDF>){return <Boundary><PDF {...props}/></Boundary>;}
export function NebulaKnowledgeNetwork(props:ComponentProps<typeof Nebula>){return <Boundary><Nebula {...props}/></Boundary>;}
export function Network(props:ComponentProps<typeof Graph>){return <Boundary><Graph {...props}/></Boundary>;}
export function PaperRelations(props:ComponentProps<typeof Relations>){return <Boundary><Relations {...props}/></Boundary>;}
export function ProposalWorkbench(props:ComponentProps<typeof Proposal>){return <Boundary><Proposal {...props}/></Boundary>;}
export function KnowledgeCards(props:ComponentProps<typeof Cards>){return <Boundary><Cards {...props}/></Boundary>;}
export function StorageSettings(props:ComponentProps<typeof Storage>){return <Boundary><Storage {...props}/></Boundary>;}
export function WordPanel(){return <Boundary><Word/></Boundary>;}
