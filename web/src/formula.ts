import type {Bar} from './indicators';

type Series=(number|null)[];
type Node=(bars:Bar[])=>Series;
const fields:Record<string,keyof Bar>={O:'open',OPEN:'open',H:'high',HIGH:'high',L:'low',LOW:'low',C:'close',CLOSE:'close',V:'volume',VOL:'volume',VOLUME:'volume'};
const tokensOf=(source:string)=>{
 if(source.length>240)throw Error('公式最多 240 个字符');
 const tokens=source.toUpperCase().match(/[A-Z_][A-Z_0-9]*|(?:\d+(?:\.\d*)?|\.\d+)|[()+\-*/,]/g)||[];
 if(tokens.join('')!==source.toUpperCase().replace(/\s+/g,''))throw Error('公式含不支持的字符');
 return tokens;
};
const number=(v:number|null)=>v!==null&&Number.isFinite(v)?v:null;
const one=(v:number,n:number)=>Array(n).fill(v) as Series;
export function formula(source:string):Node{
 const tokens=tokensOf(source),len=tokens.length;let pos=0;
 const peek=()=>tokens[pos],take=()=>tokens[pos++];
 const expect=(v:string)=>{if(take()!==v)throw Error(`缺少 ${v}`)};
 const scalar=(node:Node,bars:Bar[],label:string)=>{const values=node(bars),n=values[0];if(n===null||n===undefined||!Number.isInteger(n)||n<1||n>500||values.some(x=>x!==n))throw Error(`${label} 必须是 1–500 的整数`);return n};
 const atom=():Node=>{
  const t=take();if(!t)throw Error('公式不完整');
  if(t==='('){const node=expr();expect(')');return node}
  if(t==='-'){const node=atom();return bars=>node(bars).map(x=>number(x===null?null:-x))}
  if(/^\d|^\./.test(t)){const v=Number(t);return bars=>one(v,bars.length)}
  if(fields[t]){const key=fields[t];return bars=>bars.map(b=>Number(b[key]))}
  if(peek()!=='(')throw Error(`未知变量 ${t}`);
  take();const args:Node[]=[];if(peek()!==')'){args.push(expr());while(peek()===','){take();args.push(expr())}}expect(')');
  if(['SMA','EMA','REF','HHV','LLV'].includes(t)){
   if(args.length!==2)throw Error(`${t} 需要两个参数`);
   return bars=>{const values=args[0](bars),n=scalar(args[1],bars,t);let last:number|null=null;
    return values.map((x,i)=>{if(t==='REF')return i>=n?values[i-n]:null;
     const window=values.slice(i-n+1,i+1);if(t==='EMA'){if(x===null)return null;last=last===null?x:last+(x-last)*2/(n+1);return last}
     if(window.length<n||window.some(v=>v===null))return null;
     if(t==='SMA')return window.reduce<number>((a,v)=>a+(v||0),0)/n;
     return t==='HHV'?Math.max(...window as number[]):Math.min(...window as number[])});
   };
  }
  if(t==='ABS'&&args.length===1)return bars=>args[0](bars).map(x=>x===null?null:Math.abs(x));
  if((t==='MAX'||t==='MIN')&&args.length===2)return bars=>{const a=args[0](bars),b=args[1](bars);return a.map((v,i)=>v===null||b[i]===null?null:t==='MAX'?Math.max(v,b[i]!):Math.min(v,b[i]!))};
  throw Error(`函数 ${t} 不受支持或参数数量不对`);
 };
 const product=():Node=>{let left=atom();while(peek()==='*'||peek()==='/'){const op=take(),right=atom(),prev=left;left=bars=>{const a=prev(bars),b=right(bars);return a.map((v,i)=>number(v===null||b[i]===null||op==='/'&&b[i]===0?null:op==='*'?v*b[i]!:v/b[i]!))}}return left};
 const expr=():Node=>{let left=product();while(peek()==='+'||peek()==='-'){const op=take(),right=product(),prev=left;left=bars=>{const a=prev(bars),b=right(bars);return a.map((v,i)=>number(v===null||b[i]===null?null:op==='+'?v+b[i]!:v-b[i]!))}}return left};
 const result=expr();if(pos!==len)throw Error(`公式在 ${peek()} 附近无法解析`);return bars=>bars.length?result(bars):[];
}
