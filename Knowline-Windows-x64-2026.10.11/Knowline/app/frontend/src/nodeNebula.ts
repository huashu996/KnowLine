const textures=new Map<string,string>();
export type CloudParticle={x:number;y:number;r:number;opacity:number;phase:number};
const fringes=new Map<string,CloudParticle[]>();
export const nodeNebulaFringe=(variant:number,small:boolean)=>fringes.get(variant%24+':'+small)||[];
export const nodeNebulaStats={generations:0,durationMs:0};
export const nodeNebulaAsset='/media/paper-nodes/user-round-nebula-v4-20261006.png';
let cloud:HTMLImageElement|null=null,prepared:Promise<boolean>|null=null;
export function prepareNodeNebula(){if(prepared)return prepared;prepared=new Promise(resolve=>{const image=new Image();image.onload=()=>{cloud=image;resolve(true);};image.onerror=()=>resolve(false);image.src=nodeNebulaAsset;});return prepared;}
export function nodeNebulaLoaded(){return Boolean(cloud);}
const smooth=(v:number)=>{const t=Math.max(0,Math.min(1,v));return t*t*(3-2*t);};
const seeded=(i:number)=>((Math.imul(i+7919,2246822507)>>>0)%100000)/100000;
export function nodeNebulaUri(color:string,variant:number,small=false,unknown=false,_density=.4){
 const key=color+':'+variant%24+':'+small+':'+unknown+':'+Boolean(cloud);if(textures.has(key))return textures.get(key)!;
 const started=performance.now(),canvas=document.createElement('canvas'),size=small?256:512;canvas.width=canvas.height=size;const ctx=canvas.getContext('2d')!;
 if(cloud){ctx.translate(size/2,size/2);ctx.rotate((variant%4-1.5)*.12);ctx.drawImage(cloud,-size*.4,-size*.4,size*.8,size*.8);ctx.resetTransform();const pixels=ctx.getImageData(0,0,size,size),channels=color.startsWith('#')?[1,3,5].map(i=>parseInt(color.slice(i,i+2),16)):(color.match(/\d+/g)||[]).map(Number);
  for(let i=0;i<pixels.data.length;i+=4){const x=i/4%size,y=Math.floor(i/4/size),r=Math.hypot(x-size/2,y-size/2)/(size*.343),l=(pixels.data[i]*.2126+pixels.data[i+1]*.7152+pixels.data[i+2]*.0722)/255;
   const fade=1-smooth((r-.58)/.42),core=Math.exp(-Math.pow(r/.11,2)),highlight=Math.min(.94,Math.pow(l,3)*.7+core*.65),shade=.56+.44*Math.sqrt(l);
   pixels.data[i+3]=Math.round(255*Math.pow(pixels.data[i+3]/255,.68)*Math.pow(fade,1.3)*(.82+.18*Math.sqrt(l)));
   for(let k=0;k<3;k++)pixels.data[i+k]=Math.round((channels[k]??180)*shade*(1-highlight)+255*highlight);
  }
  ctx.putImageData(pixels,0,0);
  const fringe:CloudParticle[]=Array.from({length:small?48:72},(_,i)=>{const a=seeded(i*17+variant%24*31)*Math.PI*2,r=.25+.115*seeded(i*53+variant%24*7);return {x:Math.cos(a)*r,y:Math.sin(a)*r,r:.0015+.002*seeded(i*71),opacity:.06+.15*seeded(i*11),phase:seeded(i*19)*8};});
  fringes.set(variant%24+':'+small,fringe);
 }
 const uri=canvas.toDataURL('image/png');if(textures.size>=48)textures.delete(textures.keys().next().value!);textures.set(key,uri);
 if(cloud){nodeNebulaStats.generations++;nodeNebulaStats.durationMs+=performance.now()-started;}return uri;
}
