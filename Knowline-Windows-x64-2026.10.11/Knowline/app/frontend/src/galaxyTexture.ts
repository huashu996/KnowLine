// A single cached decorative texture. It carries no papers, counts or relations.
let cached:HTMLCanvasElement|undefined,uri:string|undefined;
export const galaxyTextureStats={generations:0,durationMs:0,pixels:768*768};
const clamp=(v:number)=>Math.max(0,Math.min(1,v));
const random=(n:number)=>{let x=Math.imul(n+193,374761393);x=Math.imul(x^(x>>>13),1274126177);return ((x^(x>>>16))>>>0)/4294967295;};
export function galaxyTexture(){
 if(cached)return cached;
 const started=performance.now(),size=768,canvas=document.createElement('canvas');canvas.width=canvas.height=size;
 const ctx=canvas.getContext('2d')!,image=ctx.createImageData(size,size),grids=[16,32,64,128].map(n=>({n,values:Float32Array.from({length:(n+1)*(n+1)},(_,i)=>random(i+n*951))}));
 const noise=(x:number,y:number)=>grids.reduce((sum,g,k)=>{const gx=clamp(x)*g.n,gy=clamp(y)*g.n,ix=Math.min(g.n-1,Math.floor(gx)),iy=Math.min(g.n-1,Math.floor(gy)),tx=gx-ix,ty=gy-iy,sx=tx*tx*(3-2*tx),sy=ty*ty*(3-2*ty),a=g.values[iy*(g.n+1)+ix],b=g.values[iy*(g.n+1)+ix+1],c=g.values[(iy+1)*(g.n+1)+ix],d=g.values[(iy+1)*(g.n+1)+ix+1];return sum+((a+(b-a)*sx)*(1-sy)+(c+(d-c)*sx)*sy)*[.46,.29,.16,.09][k];},0);
 for(let iy=0;iy<size;iy++)for(let ix=0;ix<size;ix++){
  const px=(ix-size/2)/(size/2),py=(iy-size/2)/(size/2),x=px*.985+py*.174,y=-px*.174+py*.985;
  const r=Math.hypot(x*1.12,y*.94),theta=Math.atan2(y*.94,x*1.12),n=noise(ix/size,iy/size);
  const phase=theta*2-4.9*Math.log(r+.09)+(n-.5)*1.45;
  const arm=Math.exp(-Math.pow(Math.sin(phase/2)/.36,2)),edge=Math.exp(-Math.pow(Math.sin((phase+.42)/2)/.12,2));
  const taper=Math.exp(-Math.pow(r/.76,4))*clamp((1.02-r)*6),inner=clamp((r-.13)*7);
  const cloud=(.08+.52*arm+.13*edge)*taper*inner*(.36+1.45*n);
  const lane=Math.exp(-Math.pow(Math.sin((phase-.31-(n-.5)*.5)/2)/.085,2))*clamp((r-.18)*9)*clamp((.78-r)*8);
  const bulge=.29*Math.exp(-Math.pow(r/.3,2))*(.45+n);
  const core=Math.exp(-x*x/.012-y*y/.057);
  const alpha=clamp((cloud+bulge)*(1-lane*.86)+core*.97),warm=clamp(core*2+bulge*2);
  const p=(iy*size+ix)*4;image.data[p]=Math.round(126+warm*125+edge*17);image.data[p+1]=Math.round(152+warm*99+edge*14);image.data[p+2]=Math.round(179+warm*67+edge*12);image.data[p+3]=Math.round(alpha*255);
 }
 ctx.putImageData(image,0,0);
 // Small stars collect along the arm ridges; empty sky remains empty.
 for(let i=0;i<5200;i++){
  const r=.13+Math.pow(random(i+7000),.62)*.8,arm=i%2,a=2.45*Math.log(r+.09)+arm*Math.PI+(random(i+25000)-.5)*.5;
  const x=Math.cos(a)*r/1.12,y=Math.sin(a)*r/.94,n=noise(clamp((x+1)/2),clamp((y+1)/2));
  if(random(i+48000)>.25+n*.8)continue;
  const px=(x*.985-y*.174)*size/2+size/2,py=(x*.174+y*.985)*size/2+size/2,star=.25+random(i+18000)*.8;
  ctx.fillStyle=`rgba(${i%17===0?'244,221,174':'187,216,244'},${(.16+random(i+30000)*.49)*(1-r*.5)})`;ctx.fillRect(px,py,star,star);
 }
 cached=canvas;galaxyTextureStats.generations++;galaxyTextureStats.durationMs=performance.now()-started;return canvas;
}
export function galaxyTextureUri(){if(!uri)uri=galaxyTexture().toDataURL('image/png');return uri;}
