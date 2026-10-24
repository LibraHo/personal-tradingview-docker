export const secureChart=location.pathname==='/chart';
let csrf='';
export function setChartCsrf(value:string){csrf=value}
// Keep trade requests on their existing origin and authentication path.
// Only the chart's API calls use the authenticated, read-only-service gateway.
if(secureChart){
 const originalFetch=window.fetch.bind(window);
 window.fetch=(input:RequestInfo|URL,init?:RequestInit)=>{
  if(typeof input==='string'&&input.startsWith('/api/')&&!input.startsWith('/api/trade/')){
   const headers=new Headers(init?.headers);
   if(init?.method&&!['GET','HEAD'].includes(init.method.toUpperCase()))headers.set('X-CSRF-Token',csrf);
   return originalFetch('/api/market/'+input.slice(5),{...init,headers});
  }
  return originalFetch(input,init);
 };
}
