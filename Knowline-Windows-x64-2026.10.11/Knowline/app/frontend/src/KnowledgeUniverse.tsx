import {useEffect,useRef} from 'react';
import * as THREE from 'three';
import {galaxyTexture} from './galaxyTexture';

// Normalized anchors are shared with the HTML controls. These are spatial
// positions, not semantic relationships; only supplied relations draw cross-links.
export function clusterAnchors(count:number){
 const layouts:Record<number,number[][]>={
  1:[[.5,.24]],2:[[.2,.43],[.8,.43]],
  3:[[.5,.24],[.18,.48],[.82,.48]],
  4:[[.5,.22],[.17,.45],[.83,.45],[.73,.64]],
  5:[[.5,.22],[.16,.44],[.84,.44],[.24,.64],[.76,.64]],
  6:[[.34,.23],[.67,.23],[.15,.45],[.85,.45],[.25,.64],[.75,.64]],
  7:[[.25,.23],[.5,.2],[.75,.23],[.14,.45],[.86,.45],[.26,.64],[.74,.64]],
  8:[[.32,.2],[.68,.2],[.14,.35],[.86,.35],[.14,.65],[.86,.65],[.32,.64],[.68,.64]],
 };
 return (layouts[Math.min(8,count)]||[]).map(([x,y])=>({x,y}));
}
export const clusterColors=['#c5b8ee','#a5d8ca','#e7cc91','#a0bfdc','#bed2ce','#c7c5df','#d8c598','#a9cfc8'];
type Relation={from:number;to:number;origin:string};

export default function KnowledgeUniverse({childrenCount,zoom,reduced,relations=[],active=-1,tree=false,focusColor=clusterColors[0]}:{childrenCount:number;zoom:number;reduced:boolean;relations?:Relation[];active?:number;tree?:boolean;focusColor?:string}){
 const mount=useRef<HTMLDivElement>(null),activeRef=useRef(active),renderRef=useRef<(()=>void)|null>(null);
 activeRef.current=active;
 useEffect(()=>{renderRef.current?.();},[active]);
 useEffect(()=>{
  if(!mount.current)return;
  const host=mount.current,scene=new THREE.Scene();let renderer:THREE.WebGLRenderer;
  try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});}catch{return;}
  renderer.setPixelRatio(Math.min(2,devicePixelRatio));renderer.setClearColor(0x141817,0);host.appendChild(renderer.domElement);
  // Fixed normalized camera coordinates keep cards aligned on resize. The
  // scene itself is decorative; keyboard and WebGL fallback use the HTML cards.
  const camera=new THREE.OrthographicCamera(-6,6,4,-4,.1,60);camera.position.z=15;
  const root=new THREE.Group();scene.add(root);
  const seed=(n:number)=>((Math.sin(n*127.1)*43758.5453)%1+1)%1;
  const anchor=(x:number,y:number)=>new THREE.Vector3((x-.5)*12,(.5-y)*8,0);
  const center=anchor(tree?.09:.5,.48),anchors=tree?[{x:.30,y:.48}]:clusterAnchors(childrenCount);
  const dots=document.createElement('canvas');dots.width=dots.height=64;
  const ctx=dots.getContext('2d')!,gradient=ctx.createRadialGradient(32,32,0,32,32,32);
  gradient.addColorStop(0,'#fff');gradient.addColorStop(.16,'#fff');gradient.addColorStop(.4,'rgba(255,255,255,.25)');gradient.addColorStop(1,'rgba(255,255,255,0)');ctx.fillStyle=gradient;ctx.fillRect(0,0,64,64);
  const pointTexture=new THREE.CanvasTexture(dots);
  const spiralTexture=new THREE.CanvasTexture(galaxyTexture());spiralTexture.colorSpace=THREE.SRGBColorSpace;
  const fog=document.createElement('canvas');fog.width=fog.height=256;
  const fogContext=fog.getContext('2d')!;
  for(let i=0;i<50;i++){
   const a=i*.37,d=20+seed(i+54)*70,x=128+Math.cos(a)*d,y=128+Math.sin(a)*d*.75,r=12+seed(i+771)*35;
   const haze=fogContext.createRadialGradient(x,y,0,x,y,r);haze.addColorStop(0,'rgba(220,232,255,.15)');haze.addColorStop(.45,'rgba(160,180,210,.07)');haze.addColorStop(1,'rgba(120,150,180,0)');fogContext.fillStyle=haze;fogContext.fillRect(x-r,y-r,r*2,r*2);
  }
  const fogTexture=new THREE.CanvasTexture(fog);
  function points(group:THREE.Object3D,positions:number[],color:number|string,size:number,opacity:number){
   const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
   const object=new THREE.Points(geometry,new THREE.PointsMaterial({color,size,map:pointTexture,transparent:true,opacity,blending:THREE.AdditiveBlending,depthWrite:false}));group.add(object);return object;
  }
  function lines(group:THREE.Object3D,positions:number[],color:number|string,opacity:number){
   const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
   group.add(new THREE.LineSegments(geometry,new THREE.LineBasicMaterial({color,transparent:true,opacity,depthWrite:false})));
  }
  const stars:number[]=[];for(let i=0;i<420;i++)stars.push((seed(i+1)-.5)*12,(seed(i+701)-.5)*8,-4);
  points(scene,stars,0xc7d7ed,1.4,.38);
  function halo(group:THREE.Object3D,color:number|string,size:number,opacity:number,x=0,y=0){
   const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:pointTexture,color,transparent:true,opacity,blending:THREE.AdditiveBlending,depthWrite:false}));
   sprite.position.set(x,y,-.2);sprite.scale.set(size,size,1);group.add(sprite);return sprite;
  }
  function cloud(position:THREE.Vector3,r:number,color:number|string,index:number){
   const group=new THREE.Group();group.position.copy(position);root.add(group);
   if(index===0){
    const galaxy=new THREE.Sprite(new THREE.SpriteMaterial({map:spiralTexture,color:0xffffff,transparent:true,opacity:1,depthWrite:false}));
    galaxy.scale.set(r*4.65,r*4.9,1);galaxy.position.z=-.35;group.add(galaxy);return group;
   }
   // Volumetric spiral dust replaces the dense triangulated wire shells.
   // Only a few continuous filaments remain, so each nucleus reads as a nebula.
   halo(group,color,r*.26,.5);
   const mist=new THREE.Sprite(new THREE.SpriteMaterial({map:fogTexture,color:index===0?0xb9bfdc:color,transparent:true,opacity:.3,blending:THREE.AdditiveBlending,depthWrite:false}));mist.scale.set(r*3.3,r*3.3,1);group.add(mist);
   const dust:number[]=[],outer:number[]=[],bright:number[]=[];
   for(let i=0;i<(index===0?3400:620);i++){
    const distance=r*Math.sqrt(seed(i+index*37+219)),arm=i%3;
    const a=distance/r*6.4+arm*Math.PI*2/3+(seed(i+481)-.5)*.7;
    const spread=(seed(i+817)-.5)*r*.32;
    dust.push(Math.cos(a)*distance,Math.sin(a)*distance*.83+spread,(seed(i+992)-.5)*r*.55);
    if(i%5===0){const angle=seed(i+129)*Math.PI*2,d=r*(.8+seed(i+341)*.48);outer.push(Math.cos(angle)*d,Math.sin(angle)*d*.86,(seed(i+631)-.5)*r);}
    if(i%43===0)bright.push(Math.cos(a)*distance,Math.sin(a)*distance*.83+spread,.1);
   }
   points(group,dust,index===0?0xb8c7d9:color,index===0?1.1:1.1,.58);
   points(group,outer,index===0?0x9fbfc7:color,1.2,.4);
   points(group,bright,index===0?0xfff4df:color,2.8,.95);
   for(let arm=0;arm<(index===0?4:2);arm++){
    const vertices:THREE.Vector3[]=[];
    for(let i=0;i<=100;i++){const t=i/100,a=t*4.2+arm*Math.PI*.5,d=r*(.2+t*.82);vertices.push(new THREE.Vector3(Math.cos(a)*d,Math.sin(a)*d*.83,Math.sin(a*2)*r*.12));}
    const geometry=new THREE.BufferGeometry().setFromPoints(vertices);
    group.add(new THREE.Line(geometry,new THREE.LineBasicMaterial({color,transparent:true,opacity:0,depthWrite:false})));
   }
   halo(group,0xffffff,r*.24,.6);
   return group;
  }
  const core=cloud(center,tree?.59:1.46,0xc8d2df,0);
  const satellites=anchors.map((p,i)=>cloud(anchor(p.x,p.y),tree?.49:.38,tree?focusColor:clusterColors[i],i+1));
  const paths:THREE.CubicBezierCurve3[]=[];
  satellites.forEach((target,i)=>{
   const end=target.position.clone(),delta=end.clone().sub(center);
   const curve=new THREE.CubicBezierCurve3(center.clone(),center.clone().add(delta.clone().multiplyScalar(.36)).add(new THREE.Vector3(0,.22,.4)),end.clone().sub(delta.clone().multiplyScalar(.2)),end);
   paths.push(curve);
   // Parent-child connections are grounded in the displayed hierarchy.
   const geometry=new THREE.BufferGeometry().setFromPoints(curve.getPoints(70));
   scene.add(new THREE.Line(geometry,new THREE.LineBasicMaterial({color:0xffefd0,transparent:true,opacity:.85,depthWrite:false})));
  });
  const crossEdges:{edge:THREE.Line;from:number;to:number}[]=[];
  for(const rel of relations){
   const from=satellites[rel.from],to=satellites[rel.to];if(!from||!to)continue;
   const mid=from.position.clone().add(to.position).multiplyScalar(.5);mid.z=.5;mid.y+=.2;
   const geometry=new THREE.BufferGeometry().setFromPoints(new THREE.QuadraticBezierCurve3(from.position,mid,to.position).getPoints(50));
   const material=rel.origin==='ai_suggested'?new THREE.LineDashedMaterial({color:0xffe394,dashSize:.08,gapSize:.05,transparent:true,opacity:.7}):new THREE.LineBasicMaterial({color:rel.origin==='verified_citation'?0xffe394:0xffffff,transparent:true,opacity:.75});
   const edge=new THREE.Line(geometry,material);edge.computeLineDistances();scene.add(edge);crossEdges.push({edge,from:rel.from,to:rel.to});
  }
  const flowing=points(scene,new Array(paths.length*3*3).fill(0),0xe0e4cc,4,.8);
  const particlePositions=flowing.geometry.attributes.position;
  let frame=0,disposed=false;
  const render=(time:number)=>{
   paths.forEach((path,i)=>{for(let j=0;j<3;j++){const p=path.getPoint((time*.025+j/3+i*.13)%1);particlePositions.setXYZ(i*3+j,p.x,p.y,p.z);}});particlePositions.needsUpdate=true;
   core.scale.setScalar(zoom);
   satellites.forEach((cluster,i)=>{cluster.rotation.y=.3;cluster.rotation.z=reduced?i:time*.025+i;cluster.scale.setScalar(zoom*(activeRef.current===i?1.12:1));});
   let visibleRelations=0;crossEdges.forEach(({edge,from,to})=>{edge.visible=activeRef.current>=0&&(from===activeRef.current||to===activeRef.current)&&visibleRelations++<3;});
   renderer.render(scene,camera);
  };
  renderRef.current=()=>render(reduced?0:performance.now()/1000);
  const resize=()=>{renderer.setSize(host.clientWidth,Math.max(1,host.clientHeight));render(reduced?0:performance.now()/1000);};
  const observer=new ResizeObserver(resize);observer.observe(host);resize();
  const tick=()=>{frame=0;if(disposed||document.hidden)return;render(performance.now()/1000);if(!reduced)frame=requestAnimationFrame(tick);};
  const visibility=()=>{cancelAnimationFrame(frame);frame=0;if(!document.hidden)tick();};document.addEventListener('visibilitychange',visibility);visibility();
  return()=>{disposed=true;renderRef.current=null;cancelAnimationFrame(frame);document.removeEventListener('visibilitychange',visibility);observer.disconnect();scene.traverse(object=>{const drawable=object as THREE.Mesh;drawable.geometry?.dispose();const materials=Array.isArray(drawable.material)?drawable.material:[drawable.material];materials.forEach(material=>material?.dispose());});pointTexture.dispose();fogTexture.dispose();spiralTexture.dispose();renderer.dispose();renderer.domElement.remove();};
 },[childrenCount,zoom,reduced,tree,focusColor,JSON.stringify(relations)]);
 return <div ref={mount} className="universe-canvas" aria-hidden="true"/>;
}

