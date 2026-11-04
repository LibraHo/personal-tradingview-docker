import ts from 'typescript';
import {readFileSync} from 'node:fs';
const cache=new Map();
export function moduleUrl(name){
 if(cache.has(name))return cache.get(name);
 let js=ts.transpileModule(readFileSync(new URL(`./src/${name}.ts`,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
 js=js.replace(/from ['"]\.\/([^'"]+)['"]/g,(_,dependency)=>`from '${moduleUrl(dependency)}'`);
 const url='data:text/javascript;base64,'+Buffer.from(js).toString('base64');cache.set(name,url);return url;
}
export const loadTS=name=>import(moduleUrl(name));
