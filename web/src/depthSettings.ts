import {useSyncExternalStore} from 'react';

type Settings={enabled:boolean;amount:number;qty:number;count:number;cached:boolean};
const defaults:Settings={enabled:false,amount:100000,qty:0,count:3,cached:false};
const stores=new Map<string,ReturnType<typeof createStore>>();

function createStore(symbol:string){
 const url='/api/settings/depth-'+encodeURIComponent(symbol);
 const key='depth-settings:'+symbol;
 let settings=defaults;
 try{settings={...defaults,...JSON.parse(localStorage.getItem(key)||'{}')}}catch{}
 let snapshot={settings,ready:false,saved:'读取设置…'};
 const listeners=new Set<()=>void>();
 let loading=false,saving=false,dirty=false,timer:ReturnType<typeof setTimeout>|undefined;
 function publish(next:Partial<typeof snapshot>){
  snapshot={...snapshot,...next};
  if(next.settings)try{localStorage.setItem(key,JSON.stringify(next.settings))}catch{}
  listeners.forEach(notify=>notify());
 }
 function release(){
  if(!listeners.size&&!loading&&!saving&&!dirty&&stores.get(symbol)===store)stores.delete(symbol);
 }
 async function read(){
  loading=true;
  try{
   const response=await fetch(url);
   if(!response.ok)throw Error();
   const {value}=await response.json();
   publish({settings:{...snapshot.settings,...value},ready:true,saved:'设置保存在 NAS'});
  }catch{publish({ready:true,saved:'暂用本机设置，NAS 设置读取失败'})}
  finally{loading=false;release()}
 }
 async function save(){
  if(saving||!dirty)return;
  saving=true;
  dirty=false;
  try{
   const response=await fetch(url,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:snapshot.settings})});
   if(!response.ok)throw Error();
   if(!dirty)publish({saved:'已保存到 NAS'});
  }catch{if(!dirty)publish({saved:'NAS 保存失败；本机仍保留设置'})}
  finally{saving=false;if(dirty){clearTimeout(timer);void save()}else release()}
 }
 const store={
  getSnapshot:()=>snapshot,
  subscribe(notify:()=>void){
   listeners.add(notify);
   if(!snapshot.ready&&!loading)void read();
   return ()=>{listeners.delete(notify);release()};
  },
  patch(update:Partial<Settings>){
   if(!snapshot.ready)return;
   publish({settings:{...snapshot.settings,...update},saved:'正在保存…'});
   dirty=true;
   clearTimeout(timer);
   timer=setTimeout(save,600);
  }
 };
 return store;
}

const unavailableSnapshot={settings:defaults,ready:false,saved:''};
const unavailable={
 getSnapshot:()=>unavailableSnapshot,
 subscribe:()=>()=>{},
 patch:(_update:Partial<Settings>)=>{}
};

function storeFor(symbol:string){
 if(!symbol.startsWith('US.'))return unavailable;
 let store=stores.get(symbol);
 if(!store){store=createStore(symbol);stores.set(symbol,store)}
 return store;
}

export function useDepthSettings(symbol:string){
 const store=storeFor(symbol);
 return {...useSyncExternalStore(store.subscribe,store.getSnapshot),patch:store.patch};
}
