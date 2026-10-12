import {useContext,useEffect,useState} from 'react';
import {LocaleContext} from './i18n';
export default function BuildInfo(){
 const zh=useContext(LocaleContext).locale==='zh',[build,setBuild]=useState<{build_id:string;built_at:string}|null>(null);
 useEffect(()=>{let live=true;fetch('/build-info.json').then(response=>response.ok?response.json():null).then(value=>{if(live&&typeof value?.build_id==='string')setBuild(value);}).catch(()=>{});return()=>{live=false;};},[]);
 if(!build)return null;
 return <details className="settings-section build-info"><summary>{zh?'版本信息':'Build information'}</summary><p>{zh?'构建版本':'Build'}: <code>{build.build_id}</code></p><p>{zh?'构建时间':'Built'}: {build.built_at}</p></details>;
}
