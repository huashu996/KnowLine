import {useMemo} from 'react';
import {galaxyTextureUri,galaxyTextureStats} from './galaxyTexture';
export default function GalaxyBackdrop(){
 const image=useMemo(galaxyTextureUri,[]);
 return <g aria-hidden="true" pointerEvents="none" data-visual-role="decorative-galaxy">
  <image href={image} x="60" y="-5" width="680" height="540" preserveAspectRatio="none" data-galaxy-layer="cached-spiral-dust" data-generation-ms={galaxyTextureStats.durationMs} data-generation-count={galaxyTextureStats.generations}/>
 </g>;
}
