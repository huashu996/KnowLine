// Spring motion adapted from luoluo-121/neural-creator-dashboard/src/neural/Home.jsx.
// Source license: PolyForm Noncommercial 1.0.0, bundled at
// public/licenses/neural-creator-dashboard.txt. No source sample data. Source media is integrated separately.
export type Spring={x:number;v:number};
export function spring(state:Spring,target:number,dt:number,k=62){
 const damping=2*Math.sqrt(k);
 state.v+=(-k*(state.x-target)-damping*state.v)*dt;
 state.x+=state.v*dt;
 return state.x;
}
export const dustSeeds=Array.from({length:85},(_,i)=>({angle:i*2.39996,speed:.035+(i*37%100)/100*.06,offset:(i*.618034)%1,size:.7+(i%5)*.32}));
