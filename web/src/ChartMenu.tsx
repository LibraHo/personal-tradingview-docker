import {useEffect,useRef,useState,type ReactNode} from 'react';

/** Native disclosure with local focus and dismissal for chart commands. */
export default function ChartMenu({label,children,active=false}:{label:string;children:ReactNode;active?:boolean}) {
 const root=useRef<HTMLDetailsElement>(null);
 const [open,setOpen]=useState(false);
 useEffect(()=>{
  if(!open)return;
  const dismiss=(e:PointerEvent)=>{if(root.current&&!root.current.contains(e.target as Node))root.current.open=false};
  const escape=(e:KeyboardEvent)=>{
   if(e.key==='Escape'&&root.current){root.current.open=false;root.current.querySelector('summary')?.focus()}
  };
  document.addEventListener('pointerdown',dismiss);
  document.addEventListener('keydown',escape);
  return ()=>{document.removeEventListener('pointerdown',dismiss);document.removeEventListener('keydown',escape)};
 },[open]);
 return <details ref={root} className={'chart-command-menu'+(active?' engaged':'')} onToggle={e=>setOpen(e.currentTarget.open)}>
  <summary>{label}</summary>
  <div className="chart-command-list" onClick={e=>{
   if((e.target as HTMLElement).closest('button')&&root.current){root.current.open=false;root.current.querySelector('summary')?.focus()}
  }}>{children}</div>
 </details>
}
