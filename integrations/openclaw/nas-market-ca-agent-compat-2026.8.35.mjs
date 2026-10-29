// OpenClaw 2026.8.35 secret-egress uses an explicit bundled CA list, which
// otherwise ignores the administrator's NODE_EXTRA_CA_CERTS for this NAS.
// Limit the compatibility fix to this one host/port; keep TLS verification on.
import fs from 'node:fs';
import https from 'node:https';
import {X509Certificate} from 'node:crypto';

const marker=Symbol.for('openclaw.nasMarketAgentCaCompat.2026.8.35');
const hostname='192.168.101.103';
const port=8443;
const caPath='/home/node/.openclaw/secrets/nas-market/ca.pem';
if(!https.Agent.prototype[marker]){
 const certificate=fs.readFileSync(caPath,'utf8');
 if(certificate.includes('PRIVATE KEY'))throw new Error('NAS CA file must contain only a public certificate');
 const parsed=new X509Certificate(certificate);
 if(!parsed.checkIP(hostname))throw new Error('NAS certificate does not cover the configured NAS IP');
 const original=https.Agent.prototype.createConnection;
 https.Agent.prototype.createConnection=function(options,...args){
  const host=options?.hostname||options?.host;
  if(host!==hostname||Number(options?.port)!==port||options.ca===undefined)return original.call(this,options,...args);
  const ca=Array.isArray(options.ca)?options.ca:[options.ca];
  return original.call(this,{...options,ca:[...ca,certificate]},...args);
 };
 Object.defineProperty(https.Agent.prototype,marker,{value:true});
}
