/* Signatur-Sync · Kernlogik (Browser + Node)
 * Portiert aus dem Python-Workflow: .eml/.msg-Parsing, robuste Signatur-
 * Extraktion (mehrere Signaturen pro Mail), CRM-Abgleich.
 * Relevante Felder: Name, Position, Firma, Adresse, Website, LinkedIn, E-Mail.
 * Die E-Mail-Adresse ist der primaere Schluessel fuer den CRM-Abgleich.
 */
(function (root) {
  "use strict";

  // ---------------------------------------------------------------- Muster
  const EMAIL_RE = /[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}/;
  const EMAIL_RE_G = /[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}/g;
  const URL_RE_G = /\b((?:https?:\/\/)?(?:www\.)?[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+(?:\/[^\s|<>]*)?)/g;
  const PHONE_RE = /(\+?\(?\d[\d\s().\-/]{5,}\d)/;
  const PHONE_RE_G = /(\+?\(?\d[\d\s().\-/]{5,}\d)/g;
  const LINKEDIN_RE = /(?:https?:\/\/)?(?:[a-z]{2,3}\.)?linkedin\.com\/(?:in|company|pub)\/[^\s|<>,)]+/i;
  const EMAIL_NOISE = /^(image\d|cid|mm|emns|noreply|no-reply|mailer)/i;

  const GREETINGS = [
    "mit freundlichen grüßen","mit freundlichen gruessen","freundliche grüße",
    "freundliche gruesse","viele grüße","viele gruesse","beste grüße",
    "beste gruesse","herzliche grüße","liebe grüße","mit besten grüßen",
    "mfg","lg","best regards","kind regards","warm regards","best wishes",
    "regards","cheers","sincerely","yours sincerely","thanks and regards",
    "thank you","vielen dank","danke","with kind regards"
  ];
  const PHONE_LABELS = {
    phone:["tel","tel.","phone","fon","fixed","festnetz","office","büro","buero","t:","p:","ph:","direct","durchwahl"],
    mobile:["mobil","mobile","cell","cellular","handy","m:","mob","mo:"],
    fax:["fax","f:","telefax"]
  };
  const COMPANY_HINTS = ["gmbh","ag","kg","kgaa","ohg","se","e.u.","e.k.","gbr","ug",
    "mbh","e.v.","ev","inc","inc.","llc","ltd","ltd.","plc","corp","corporation",
    "co.","& co","group","gruppe","holding","partners","sarl","s.a.","b.v.","bv",
    "n.v.","srl","oy","limited","technologies","solutions","systems"];
  const TITLE_KEYWORDS = {
    "C-Level":["ceo","cfo","cto","coo","cio","cmo","cdo","geschäftsführer","geschaeftsfuehrer","geschäftsführerin","geschäftsführende","vorstand","vorständin","managing director","owner","inhaber","inhaberin","gesellschafter","president","präsident","partner","partnerin","founder","co-founder","gründer","mitgründer","geschäftsleitung"],
    "Leitung":["head of","head","leiter","leiterin","leitung","director","direktor","direktorin","vp ","vice president","vorstandsvorsitz","abteilungsleiter","abteilungsleiterin","teamleiter","teamleiterin","bereichsleiter","bereichsleiterin","prokurist","prokuristin","standortleiter","niederlassungsleiter"],
    "Management":["manager","managerin","lead","principal","senior manager","projektleiter","projektleiterin","key account","account manager","account executive","product owner","produktmanager","teamlead","team lead","scrum master"],
    "Fachkraft":["engineer","developer","entwickler","entwicklerin","consultant","berater","beraterin","specialist","spezialist","analyst","referent","referentin","sachbearbeiter","sachbearbeiterin","architect","designer","scientist","expert","associate","ingenieur","ingenieurin","techniker","recruiter","recruiting","controller","buchhalter","buchhalterin","assistenz","assistent","assistentin","assistant","kundenberater","kundenbetreuer","sales","vertrieb","marketing"]
  };
  const DECISION_MAKER_LEVELS = new Set(["C-Level","Leitung"]);
  const NON_NAME_RE = /@|http|www|tel|mobil|fax|gmbh|\bag\b|\d|straße|strasse|str\.|platz|e-mail|mail:|phone|grüße|gruesse|gruß|regards|linkedin/i;
  const GRADE_RE = /\b(dr|prof|dipl|mag|ing|mba|msc|bsc|ba|ma)\.?\b/gi;
  const STREET_RE = /(?:stra(?:ß|ss)e|str\.|gasse|weg|platz|allee|ring|chaussee|damm|ufer)\b|\b(?:road|rd\.|street|st\.|ave|avenue|lane|boulevard|blvd)\b/i;
  const PLZ_RE = /\b([A-Z]{1,2}-)?(\d{4,5})\s+([A-ZÄÖÜ][\wäöüß.\-]+)/;
  const COUNTRY_RE = /^\s*(deutschland|germany|österreich|oesterreich|austria|schweiz|switzerland|liechtenstein)\s*$/i;
  const BOUNDARY_RE = /^\s*(-{2,}\s*(original|ursprüngliche|forwarded|weitergeleitete)|(von|from|gesendet|sent|an|to|cc|betreff|subject|datum|date)\s*:|(am|on)\b.*\b(schrieb|wrote)\b|(gesendet|sent)\s+(von|from)\s+mein|_{5,})/i;

  // ---------------------------------------------------------------- Utils
  function escapeHtml(v){return (v||"").replace(/[&<>"']/g,function(c){return ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c];});}
  function allMatches(re,text){const out=[];let m;re.lastIndex=0;while((m=re.exec(text))!==null){out.push(m);if(m.index===re.lastIndex)re.lastIndex++;}return out;}
  function norm(v){return (v||"").toLowerCase().split(/\s+/).filter(Boolean).join(" ");}
  function hasCompanyHint(text){const low=(text||"").toLowerCase();return COMPANY_HINTS.some(function(h){return new RegExp("(?<![a-z])"+h.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")+"(?![a-z])").test(low);});}
  function isGreeting(line){const low=line.trim().toLowerCase().replace(/[,.!]+$/,"").trim();return GREETINGS.indexOf(low)>=0||GREETINGS.some(function(g){return low.startsWith(g);});}

  // -------------------------------------------------------------- HTML→Text
  function htmlToText(html){
    if(!html) return "";
    let t=html.replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi," ");
    t=t.replace(/<\s*br\s*\/?\s*>/gi,"\n").replace(/<\/\s*(p|div|tr|li|h[1-6])\s*>/gi,"\n").replace(/<[^>]+>/g,"");
    t=t.replace(/&nbsp;/gi," ").replace(/&amp;/gi,"&").replace(/&lt;/gi,"<").replace(/&gt;/gi,">").replace(/&quot;/gi,'"').replace(/&#39;/gi,"'").replace(/&auml;/gi,"ä").replace(/&ouml;/gi,"ö").replace(/&uuml;/gi,"ü").replace(/&szlig;/gi,"ß");
    const lines=t.split(/\r?\n/).map(function(l){return l.replace(/[ \t]+/g," ").trim();});
    const out=[];let blank=false;
    lines.forEach(function(l){if(l){out.push(l);blank=false;}else if(!blank){out.push("");blank=true;}});
    return out.join("\n").trim();
  }

  // ---------------------------------------------------------- Feld-Heuristik
  function classifyPhoneLine(line){const low=line.toLowerCase();for(const f in PHONE_LABELS){if(PHONE_LABELS[f].some(function(l){return low.indexOf(l)>=0;}))return f;}return null;}
  function detectSeniority(title){const low=(title||"").toLowerCase();for(const lvl in TITLE_KEYWORDS){if(TITLE_KEYWORDS[lvl].some(function(kw){return low.indexOf(kw)>=0;}))return lvl;}return "";}
  function looksLikeName(line){let s=line.trim().replace(/^\|+|\|+$/g,"").trim();if(!s||NON_NAME_RE.test(s))return false;s=s.replace(GRADE_RE,"");const w=s.trim().split(/[\s,]+/).filter(Boolean);if(!(w.length>1&&w.length<=4))return false;const cap=w.filter(function(x){return x[0]&&x[0]===x[0].toUpperCase()&&x[0]!==x[0].toLowerCase();}).length;return cap>=Math.max(2,w.length-1);}
  function splitName(full){const c=full.replace(GRADE_RE,"").trim();const p=c.split(/\s+/).map(function(x){return x.replace(/,+$/,"");}).filter(function(x){return x&&/[A-Za-zÀ-ÿ]/.test(x);});if(p.length>=2)return [p[0],p.slice(1).join(" ")];return [p[0]||c,""];}
  function brandTokens(value){if(!value)return [];let host=value.toLowerCase().split("@").pop();host=host.replace(/^https?:\/\//,"").split("/")[0].replace(/^www\./,"");const labels=host.split(".");const core=labels.length>=2?labels[labels.length-2]:labels[0];return core.split(/[-_]/).filter(function(t){return t.length>=3;});}
  function chooseEmail(block,fallback){const found=(block.match(EMAIL_RE_G)||[]).filter(function(e){return !EMAIL_NOISE.test(e.split("@")[0]);});const low=found.map(function(e){return e.toLowerCase();});if(fallback&&fallback.from_email&&low.indexOf(fallback.from_email)>=0)return fallback.from_email;if(low.length)return low[0];if(fallback&&fallback.from_email)return fallback.from_email;return "";}

  function findCompany(lines,used){
    for(let i=0;i<lines.length;i++){if(used.has(i))continue;if(hasCompanyHint(lines[i])){const chunks=lines[i].split(/\s*[|·•]\s*/);for(const c of chunks)if(hasCompanyHint(c))return [c.replace(/^[\s,;|]+|[\s,;|]+$/g,""),i];return [lines[i].replace(/^[\s,;|]+|[\s,;|]+$/g,""),i];}}
    return ["",-1];
  }
  function findCompanyByDomain(lines,used,domainSource){
    const toks=brandTokens(domainSource);if(!toks.length)return ["",-1];
    for(let i=0;i<lines.length;i++){if(used.has(i))continue;const ln=lines[i];if(/linkedin/i.test(ln)||EMAIL_RE.test(ln)||STREET_RE.test(ln))continue;const low=ln.toLowerCase().replace(/[^a-z0-9]/g,"");if(toks.some(function(t){return low.indexOf(t)>=0;}))return [ln.replace(/^[\s,;|]+|[\s,;|]+$/g,""),i];}
    return ["",-1];
  }
  function findAddress(lines,used){
    const parts=[];let location="";
    for(let i=0;i<lines.length;i++){if(used.has(i))continue;const ln=lines[i];const plz=ln.match(PLZ_RE);if(STREET_RE.test(ln)||plz||COUNTRY_RE.test(ln)){parts.push(ln.replace(/^[\s,;|]+|[\s,;|]+$/g,""));used.add(i);if(plz)location=plz[3].replace(/^[.\s,-]+|[.\s,-]+$/g,"");}}
    return [parts.join(", "),location];
  }

  function parseSignature(block,fallback){
    const sig={raw_block:block||"",full_name:"",first_name:"",last_name:"",job_title:"",department:"",company:"",email:"",phone:"",mobile:"",fax:"",website:"",linkedin:"",address:"",seniority:"",is_decision_maker:false,location:""};
    const lines=(block||"").split(/\r?\n/).map(function(l){return l.trim();}).filter(Boolean);
    const used=new Set();
    sig.email=chooseEmail(block||"",fallback);
    const lk=(block||"").match(LINKEDIN_RE);if(lk)sig.linkedin=lk[0].replace(/[.,;)]+$/,"");
    const urlText=(block||"").replace(EMAIL_RE_G," ");
    for(const um of allMatches(URL_RE_G,urlText)){let cand=um[1].trim().replace(/[.,;)]+$/,"");const low=cand.toLowerCase();if(cand.indexOf("@")>=0||low.indexOf("linkedin.com")>=0)continue;if(cand.indexOf(".")>=0&&!/^[\d.]+$/.test(cand)){sig.website=cand;break;}}
    for(let i=0;i<lines.length;i++){if(isGreeting(lines[i]))used.add(i);}
    for(let i=0;i<lines.length;i++){if(used.has(i)||!PHONE_RE.test(lines[i]))continue;const kind=classifyPhoneLine(lines[i])||"phone";const nums=allMatches(PHONE_RE_G,lines[i]).map(function(m){return m[1].trim();});if(!nums.length)continue;const number=nums[0];if(kind==="mobile"&&!sig.mobile)sig.mobile=number;else if(kind==="fax"&&!sig.fax)sig.fax=number;else if(!sig.phone)sig.phone=number;if(!looksLikeName(lines[i].replace(PHONE_RE_G,"")))used.add(i);}
    let nameIdx=-1;
    for(let i=0;i<lines.length;i++){if(used.has(i))continue;const chunks=lines[i].split(/\s*[|·•–-]\s+/);const head=chunks[0].trim();if(looksLikeName(head)){sig.full_name=head.replace(/^\|+|\|+$/g,"").trim();nameIdx=i;used.add(i);if(chunks.length>1&&detectSeniority(chunks[1]))sig.job_title=chunks[1].replace(/^[\s,;|]+|[\s,;|]+$/g,"");break;}}
    if(!sig.full_name&&fallback&&fallback.from_name)sig.full_name=fallback.from_name.trim();
    let comp=findCompany(lines,used);
    if(!comp[0])comp=findCompanyByDomain(lines,used,sig.website||sig.email);
    if(comp[0]){sig.company=comp[0];used.add(comp[1]);}
    if(!sig.job_title){
      let title="";
      if(nameIdx>=0&&nameIdx+1<lines.length&&!used.has(nameIdx+1)){const cand=lines[nameIdx+1];if(!EMAIL_RE.test(cand)&&!PHONE_RE.test(cand)&&!STREET_RE.test(cand)&&cand!==sig.company){title=cand.split(/\s*[|·•]\s*/)[0].replace(/^[\s,;|]+|[\s,;|]+$/g,"");used.add(nameIdx+1);}}
      if(!title){for(let i=0;i<lines.length;i++){if(used.has(i))continue;if(detectSeniority(lines[i])){title=lines[i].split(/\s*[|·•]\s*/)[0].replace(/^[\s,;|]+|[\s,;|]+$/g,"");used.add(i);break;}}}
      sig.job_title=title;
    }
    for(let i=0;i<lines.length;i++){if(used.has(i))continue;if(/\b(abteilung|department|team|bereich|unit)\b/i.test(lines[i])){sig.department=lines[i].replace(/^[\s,;|]+|[\s,;|]+$/g,"");used.add(i);break;}}
    const addr=findAddress(lines,used);sig.address=addr[0];sig.location=addr[1];
    if(sig.full_name){const sp=splitName(sig.full_name);sig.first_name=sp[0];sig.last_name=sp[1];}
    sig.seniority=detectSeniority(sig.job_title);sig.is_decision_maker=DECISION_MAKER_LEVELS.has(sig.seniority);
    return sig;
  }

  // -------------------------------------------------- Mehrere Signaturen
  function segments(text){
    const segs=[];let cur=[];
    text.split(/\r?\n/).forEach(function(ln){const s=ln.replace(/^[ \t]*>+[ \t]?/,"");if(BOUNDARY_RE.test(s)){if(cur.length)segs.push(cur);cur=[];}else cur.push(s.replace(/\s+$/,""));});
    if(cur.length)segs.push(cur);return segs;
  }
  function segmentBlock(lines){
    for(let i=0;i<lines.length;i++){if(lines[i].trim()==="--")return lines.slice(i+1).join("\n").trim();}
    let anchor=null;for(let i=0;i<lines.length;i++){if(isGreeting(lines[i]))anchor=i;}
    if(anchor!==null)return lines.slice(anchor+1).join("\n").trim();
    const nonempty=lines.filter(function(l){return l.trim();});const tail=nonempty.slice(-10).join("\n");
    if(EMAIL_RE.test(tail)||PHONE_RE.test(tail)||hasCompanyHint(tail)||LINKEDIN_RE.test(tail))return tail.trim();
    return "";
  }
  function sigMin(s){return !!(s.email||(s.full_name&&(s.company||s.job_title))||s.linkedin);}
  function mergeInto(base,extra){["full_name","first_name","last_name","job_title","department","company","phone","mobile","fax","website","linkedin","address","location","seniority"].forEach(function(f){if(!base[f]&&extra[f])base[f]=extra[f];});base.is_decision_maker=base.is_decision_maker||extra.is_decision_maker;}

  function extractAllSignatures(mail){
    let text=mail.text_body||"";
    if(!text&&mail.html_body)text=htmlToText(mail.html_body);
    let sigs=[];
    segments(text).forEach(function(seg){const block=segmentBlock(seg);if(!block)return;const s=parseSignature(block);if(sigMin(s))sigs.push(s);});
    const byKey={};const order=[];
    sigs.forEach(function(s){const key=s.email||("nc:"+norm(s.full_name)+"|"+norm(s.company));if(byKey[key])mergeInto(byKey[key],s);else{byKey[key]=s;order.push(key);}});
    let result=order.map(function(k){return byKey[k];});
    if(mail.from_email&&!result.some(function(s){return s.email===mail.from_email;})){
      const fn=norm(mail.from_name);let anchored=false;
      for(const s of result){if(!s.email&&fn&&norm(s.full_name)===fn){s.email=mail.from_email;anchored=true;break;}}
      if(!anchored&&!result.length){const s=extractFromEmail(mail);if(sigMin(s))result=[s];}
    }
    if(!result.length){const s=extractFromEmail(mail);if(sigMin(s))result=[s];}
    return result;
  }
  function extractFromEmail(mail){
    let body=mail.text_body||"";
    let block=segmentBlock(segments(body)[0]||[]);
    if(!block&&mail.html_body)block=segmentBlock(segments(htmlToText(mail.html_body))[0]||[]);
    if(!block)block=body;
    return parseSignature(block,mail);
  }

  // ------------------------------------------------------------- Abgleich
  const COMPARED_FIELDS=[["job_title","Position/Titel"],["company","Firma"],["address","Adresse"],["website","Website"],["linkedin","LinkedIn"],["department","Abteilung"],["phone","Telefon"],["mobile","Mobil"]];
  function normPhone(v){if(!v)return "";let d=v.replace(/[^\d+]/g,"");return d.startsWith("+")?d:d.replace(/^0+/,"");}
  function valuesMatch(field,a,b){if(field==="phone"||field==="mobile"){const na=normPhone(a),nb=normPhone(b);if(!na||!nb)return na===nb;return na===nb||na.slice(-7)===nb.slice(-7);}return norm(a)===norm(b);}
  function deriveSignals(sig,crm,disc){
    const out=[];const ch=new Set(disc.filter(function(d){return d.change_type==="FIELD_CHANGED";}).map(function(d){return d.field;}));
    if(ch.has("company"))out.push("🔁 Firmenwechsel erkannt – Kontakt prüfen (mögliche neue Opportunity bzw. Risiko beim alten Account).");
    if(ch.has("job_title")){let n="📈 Positionswechsel/Beförderung erkannt – Rolle im CRM aktualisieren.";if(sig.is_decision_maker)n+=" Kontakt ist jetzt Entscheider:in – für Vertrieb relevant.";out.push(n);}
    if(ch.has("address"))out.push("📍 Adresse hat sich geändert – Stammdaten aktualisieren.");
    if(ch.has("website"))out.push("🌐 Geänderte Website – Stammdaten aktualisieren.");
    if(ch.has("linkedin"))out.push("🔗 LinkedIn-Profil aktualisieren.");
    if(ch.has("phone")||ch.has("mobile"))out.push("☎️ Geänderte Telefonnummer – Stammdaten aktualisieren.");
    if(ch.has("department"))out.push("🏷️ Abteilung/Funktion hat sich geändert.");
    if(sig.is_decision_maker&&!ch.has("job_title"))out.push("⭐ Entscheider:in laut Signatur – Priorisierung im Vertrieb prüfen.");
    return out;
  }
  function findCrm(crmList,email,name){const e=(email||"").toLowerCase();if(e){const hit=crmList.find(function(c){return (c.email||"").toLowerCase()===e;});if(hit)return hit;}const n=norm(name);if(n)return crmList.find(function(c){return norm(c.full_name)===n;})||null;return null;}
  function reconcile(sig,crmList,source){
    const res={source:source||"",signature:sig,crm_contact:null,matched:false,match_key:"",discrepancies:[],business_signals:[],notes:[]};
    const crm=findCrm(crmList,sig.email,sig.full_name);
    if(!crm){
      COMPARED_FIELDS.forEach(function(f){const v=sig[f[0]];if(v)res.discrepancies.push({field:f[0],change_type:"FIELD_NEW_IN_CRM",signature_value:v,crm_value:""});});
      res.business_signals.push("🆕 Kontakt nicht im CRM gefunden – als neuen Lead/Kontakt anlegen.");
      if(sig.is_decision_maker)res.business_signals.push("⭐ Neuer Kontakt ist laut Signatur Entscheider:in.");
      return res;
    }
    res.matched=true;res.crm_contact=crm;res.match_key=(sig.email&&sig.email===(crm.email||"").toLowerCase())?"email":"name";
    COMPARED_FIELDS.forEach(function(f){const field=f[0];const sv=sig[field]||"";const cv=crm[field]||"";if(!sv)return;if(!cv)res.discrepancies.push({field:field,change_type:"FIELD_NEW_IN_CRM",signature_value:sv,crm_value:""});else if(valuesMatch(field,sv,cv))res.discrepancies.push({field:field,change_type:"MATCH",signature_value:sv,crm_value:cv});else res.discrepancies.push({field:field,change_type:"FIELD_CHANGED",signature_value:sv,crm_value:cv});});
    res.business_signals=deriveSignals(sig,crm,res.discrepancies);
    return res;
  }
  function hasActionableChanges(res){return (!res.matched)||res.discrepancies.some(function(d){return d.change_type==="FIELD_CHANGED"||d.change_type==="FIELD_NEW_IN_CRM";});}
  function tone(res){return !res.matched?"new":(hasActionableChanges(res)?"upd":"ok");}

  function analyzeEmail(loaded,crmList){
    const sigs=extractAllSignatures(loaded);
    if(!sigs.length)return {results:[],skipped:[{source:loaded.source,reason:"Keine verwertbare Signatur gefunden."}]};
    const multi=sigs.length>1;const out=[];
    sigs.forEach(function(sig,i){const src=multi?(loaded.source+"#"+(i+1)):loaded.source;const r=reconcile(sig,crmList,src);r.tone=tone(r);r.has_actionable=hasActionableChanges(r);out.push(r);});
    return {results:out,skipped:[]};
  }

  // --------------------------------------------------------------- .eml
  function decodeBytes(bytes,charset){const cs=(charset||"utf-8").toLowerCase().replace("utf8","utf-8");try{return new TextDecoder(cs).decode(bytes);}catch(e){try{return new TextDecoder("utf-8").decode(bytes);}catch(e2){return String.fromCharCode.apply(null,bytes);}}}
  function b64ToBytes(s){const clean=(s||"").replace(/[^A-Za-z0-9+/=]/g,"");const bin=(typeof atob==="function")?atob(clean):Buffer.from(clean,"base64").toString("binary");const out=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)out[i]=bin.charCodeAt(i);return out;}
  function qpToBytes(s){s=s.replace(/=\r?\n/g,"");const out=[];for(let i=0;i<s.length;i++){if(s[i]==="="&&i+2<s.length){out.push(parseInt(s.substr(i+1,2),16));i+=2;}else out.push(s.charCodeAt(i));}return new Uint8Array(out);}
  function decodeRFC2047(value){if(!value||value.indexOf("=?")<0)return value||"";return value.replace(/=\?([^?]+)\?([bBqQ])\?([^?]*)\?=/g,function(_,cs,enc,txt){let bytes;if(enc.toUpperCase()==="B")bytes=b64ToBytes(txt);else bytes=qpToBytes(txt.replace(/_/g," "));return decodeBytes(bytes,cs);});}
  function parseHeaders(headerText){const h={};const lines=headerText.split(/\r?\n/);let cur=null;for(const ln of lines){if(/^[ \t]/.test(ln)&&cur){h[cur]+=" "+ln.trim();continue;}const idx=ln.indexOf(":");if(idx>0){cur=ln.slice(0,idx).trim().toLowerCase();h[cur]=ln.slice(idx+1).trim();}}return h;}
  function getBoundary(ct){const m=(ct||"").match(/boundary="?([^";]+)"?/i);return m?m[1]:"";}
  function getCharset(ct){const m=(ct||"").match(/charset="?([^";]+)"?/i);return m?m[1]:"utf-8";}
  function decodePart(rawBody,headers){const cte=(headers["content-transfer-encoding"]||"7bit").toLowerCase();const charset=getCharset(headers["content-type"]);let bytes;if(cte.indexOf("base64")>=0)bytes=b64ToBytes(rawBody);else if(cte.indexOf("quoted-printable")>=0)bytes=qpToBytes(rawBody);else return rawBody;return decodeBytes(bytes,charset);}
  function walkParts(rawBody,headers,acc){const ct=headers["content-type"]||"text/plain";if(/multipart\//i.test(ct)){const boundary=getBoundary(ct);if(!boundary)return;const segs=rawBody.split("--"+boundary);for(let seg of segs){seg=seg.replace(/^\r?\n/,"");if(!seg||seg.startsWith("--"))continue;const sp=seg.indexOf("\r\n\r\n")>=0?seg.indexOf("\r\n\r\n"):seg.indexOf("\n\n");if(sp<0)continue;const hsep=seg.indexOf("\r\n\r\n")>=0?4:2;walkParts(seg.slice(sp+hsep),parseHeaders(seg.slice(0,sp)),acc);}}else if(/text\/plain/i.test(ct)){if(!acc.text)acc.text=decodePart(rawBody,headers);}else if(/text\/html/i.test(ct)){if(!acc.html)acc.html=decodePart(rawBody,headers);}}
  function parseAddr(value){if(!value)return ["",""];const m=value.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/);if(m)return [m[1].trim(),m[2].trim()];if(value.indexOf("@")>=0)return ["",value.trim()];return [value.trim(),""];}
  function parseEml(raw,source){
    raw=raw.replace(/\r\n/g,"\n");const sep=raw.indexOf("\n\n");
    const headerText=sep>=0?raw.slice(0,sep):raw;const bodyRaw=(sep>=0?raw.slice(sep+2):"").replace(/\n/g,"\r\n");
    const headers=parseHeaders(headerText);const fp=parseAddr(decodeRFC2047(headers["from"]||""));
    const acc={};walkParts(bodyRaw,headers,acc);
    let text=acc.text||"",html=acc.html||"";
    if(!text&&!html){if(/text\/html/i.test(headers["content-type"]||""))html=decodePart(bodyRaw,headers);else text=decodePart(bodyRaw,headers);}
    if(!text&&html)text=htmlToText(html);
    return {source:source||"",from_name:fp[0]||"",from_email:(fp[1]||"").toLowerCase(),subject:decodeRFC2047(headers["subject"]||""),date:headers["date"]||"",text_body:text||"",html_body:html||""};
  }

  // --------------------------------------------------------------- .msg (OLE/CFB)
  const ENDOFCHAIN=0xFFFFFFFE,FREESECT=0xFFFFFFFF;
  function parseMsg(uint8,source){
    const dv=new DataView(uint8.buffer,uint8.byteOffset,uint8.byteLength);
    const sg=[0xD0,0xCF,0x11,0xE0,0xA1,0xB1,0x1A,0xE1];
    for(let i=0;i<8;i++)if(uint8[i]!==sg[i])throw new Error("Keine gültige .msg/OLE-Datei");
    const sectorSize=1<<dv.getUint16(30,true),miniSize=1<<dv.getUint16(32,true);
    const firstDir=dv.getUint32(48,true),miniCutoff=dv.getUint32(56,true);
    const firstMiniFat=dv.getUint32(60,true);let firstDifat=dv.getUint32(68,true);
    const u32=function(o){return dv.getUint32(o,true);},secOff=function(s){return (s+1)*sectorSize;};
    const fatSectors=[];for(let i=0;i<109;i++){const v=u32(76+i*4);if(v!==FREESECT&&v!==ENDOFCHAIN)fatSectors.push(v);}
    let ds=firstDifat,g=0;while(ds!==ENDOFCHAIN&&ds!==FREESECT&&g++<100000){const base=secOff(ds);const per=sectorSize/4-1;for(let i=0;i<per;i++){const v=u32(base+i*4);if(v!==FREESECT&&v!==ENDOFCHAIN)fatSectors.push(v);}ds=u32(base+per*4);}
    const fat=[];fatSectors.forEach(function(fs){const base=secOff(fs);for(let i=0;i<sectorSize/4;i++)fat.push(u32(base+i*4));});
    function readChain(start,limit){const parts=[];let s=start,total=0,gg=0;while(s!==ENDOFCHAIN&&s!==FREESECT&&gg++<1e7){const off=secOff(s);parts.push(uint8.subarray(off,off+sectorSize));total+=sectorSize;s=fat[s];if(s===undefined)break;if(limit&&total>=limit)break;}const out=new Uint8Array(total);let p=0;parts.forEach(function(a){out.set(a,p);p+=a.length;});return limit?out.subarray(0,limit):out;}
    const dirBytes=readChain(firstDir);const ddv=new DataView(dirBytes.buffer,dirBytes.byteOffset,dirBytes.byteLength);
    const entries=[];for(let off=0;off+128<=dirBytes.length;off+=128){const nameLen=ddv.getUint16(off+64,true);const objType=dirBytes[off+66];if(objType===0)continue;let name="";if(nameLen>2)name=new TextDecoder("utf-16le").decode(dirBytes.subarray(off,off+nameLen-2));entries.push({name:name,objType:objType,start:ddv.getUint32(off+116,true),size:ddv.getUint32(off+120,true)});}
    const rootE=entries.find(function(e){return e.objType===5;});const miniStream=rootE?readChain(rootE.start,rootE.size):new Uint8Array(0);
    const miniFat=[];if(firstMiniFat!==ENDOFCHAIN){const mfb=readChain(firstMiniFat);const mdv=new DataView(mfb.buffer,mfb.byteOffset,mfb.byteLength);for(let i=0;i+4<=mfb.length;i+=4)miniFat.push(mdv.getUint32(i,true));}
    function readMini(start,size){const parts=[];let s=start,total=0,gg=0;while(s!==ENDOFCHAIN&&s!==FREESECT&&gg++<1e7){const off=s*miniSize;parts.push(miniStream.subarray(off,off+miniSize));total+=miniSize;s=miniFat[s];if(s===undefined)break;}const out=new Uint8Array(total);let p=0;parts.forEach(function(a){out.set(a,p);p+=a.length;});return out.subarray(0,size);}
    function streamData(e){return e.size>=miniCutoff?readChain(e.start,e.size):readMini(e.start,e.size);}
    const streams={};entries.forEach(function(e){if(e.objType===2&&e.name.indexOf("__substg1.0_")===0)streams[e.name.split("_").pop().toUpperCase()]=streamData(e);});
    function getStr(pid){let d=streams[pid+"001F"];if(d)return new TextDecoder("utf-16le").decode(d);d=streams[pid+"001E"];if(d)return decodeBytes(d,"cp1252");return "";}
    const subject=getStr("0037"),body=getStr("1000");let html="";const hb=streams["10130102"];if(hb)html=decodeBytes(hb,"utf-8");
    const headers=getStr("007D");let fromName=getStr("0C1A"),fromEmail="";["5D01","0C1F","5D02","0065"].some(function(pid){const v=getStr(pid);if(v.indexOf("@")>=0){fromEmail=v;return true;}return false;});
    let date="";if(headers){const h=parseHeaders(headers.replace(/\r\n/g,"\n"));date=h["date"]||"";const fp=parseAddr(decodeRFC2047(h["from"]||""));if(fp[1]){fromName=fp[0]||fromName;fromEmail=fp[1];}}
    let text=body;if(!text&&html)text=htmlToText(html);
    return {source:source||"",from_name:(fromName||"").trim(),from_email:(fromEmail||"").trim().toLowerCase(),subject:(subject||"").trim(),date:date,text_body:text||"",html_body:html||""};
  }

  const API={parseEml:parseEml,parseMsg:parseMsg,htmlToText:htmlToText,
    extractAllSignatures:extractAllSignatures,extractFromEmail:extractFromEmail,
    parseSignature:parseSignature,reconcile:reconcile,analyzeEmail:analyzeEmail,
    tone:tone,hasActionableChanges:hasActionableChanges,escapeHtml:escapeHtml,splitName:splitName};
  if(typeof module!=="undefined"&&module.exports)module.exports=API;
  root.SignaturCore=API;
})(typeof window!=="undefined"?window:globalThis);
