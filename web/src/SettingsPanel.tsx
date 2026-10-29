import {useEffect,useRef,type ReactNode} from 'react';
export type SettingsTab='appearance'|'indicators'|'depth'|'cache';
const tabs:{id:SettingsTab;label:string}[]=[{id:'appearance',label:'K 线与配色'},{id:'indicators',label:'指标管理'},{id:'depth',label:'盘口密集线'},{id:'cache',label:'数据与缓存'}];
export default function SettingsPanel({tab,onTab,onClose,onContentHost,children}:{tab:SettingsTab;onTab:(tab:SettingsTab)=>void;onClose:()=>void;onContentHost:(node:HTMLDivElement|null)=>void;children:ReactNode}){
 const box=useRef<HTMLDivElement>(null);
 useEffect(()=>{const before=document.activeElement as HTMLElement|null;box.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.focus();return()=>before?.focus()},[]);
 return <div className="settings-backdrop"><section className="settings-panel" ref={box} role="dialog" aria-modal="true" aria-label="统一设置" onKeyDown={e=>{
  if(e.key==='Escape'){e.stopPropagation();onClose()}
  if(e.key==='Tab'){const nodes=Array.from(box.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,a[href]')||[]).filter(node=>node.getClientRects().length>0);const first=nodes[0],last=nodes.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}}
 }}><header className="settings-heading"><div><h2>设置</h2><p>市场配色、指标位置、盘口与缓存</p></div><button aria-label="关闭设置" onClick={onClose}>关闭</button></header><nav role="tablist" aria-label="设置分类">{tabs.map(t=><button key={t.id} role="tab" aria-selected={tab===t.id} onClick={()=>onTab(t.id)}>{t.label}</button>)}</nav><div className="settings-content" ref={onContentHost}>{children}</div></section></div>;
}
