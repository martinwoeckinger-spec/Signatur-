/* Signatur-Sync · Kernlogik (Browser + Node)
 * Portiert aus dem Python-Workflow: .eml/.msg-Parsing, Signatur-Extraktion,
 * CRM-Abgleich. Keine Abhaengigkeiten – laeuft im Browser und unter Node.
 */
(function (root) {
  "use strict";

  // ---------------------------------------------------------------- Muster
  const EMAIL_RE = /[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}/;
  const EMAIL_RE_G = /[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}/g;
  const URL_RE_G = /\b((?:https?:\/\/)?(?:www\.)?[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+(?:\/[^\s|<>]*)?)/g;
  const PHONE_RE = /(\+?\(?\d[\d\s().\-/]{5,}\d)/;
  const PHONE_RE_G = /(\+?\(?\d[\d\s().\-/]{5,}\d)/g;
  const LINKEDIN_RE = /(https?:\/\/)?([a-z]{2,3}\.)?linkedin\.com\/[^\s|<>]+/i;

  const GREETINGS = [
    "mit freundlichen grüßen", "mit freundlichen gruessen", "freundliche grüße",
    "freundliche gruesse", "viele grüße", "viele gruesse", "beste grüße",
    "beste gruesse", "herzliche grüße", "liebe grüße", "mfg", "lg",
    "best regards", "kind regards", "warm regards", "best wishes",
    "regards", "cheers", "sincerely", "yours sincerely", "thanks and regards",
    "thank you", "vielen dank", "danke"
  ];
  const PHONE_LABELS = {
    phone: ["tel", "tel.", "phone", "fon", "fixed", "festnetz", "office", "büro",
            "buero", "t:", "p:", "ph:", "direct", "durchwahl"],
    mobile: ["mobil", "mobile", "cell", "cellular", "handy", "m:", "mob", "mo:"],
    fax: ["fax", "f:", "telefax"]
  };
  const COMPANY_HINTS = ["gmbh", "ag", "kg", "ohg", "se", "e.u.", "e.k.", "gbr",
    "ug", "mbh", "inc", "inc.", "llc", "ltd", "ltd.", "plc", "corp",
    "corporation", "co.", "group", "gruppe", "holding", "partners", "& co"];
  const TITLE_KEYWORDS = {
    "C-Level": ["ceo", "cfo", "cto", "coo", "cio", "cmo", "cdo", "geschäftsführer",
      "geschaeftsfuehrer", "geschäftsführerin", "vorstand", "managing director",
      "owner", "inhaber", "gesellschafter", "president", "partner"],
    "Leitung": ["head of", "leiter", "leiterin", "leitung", "director", "direktor",
      "vp ", "vice president", "vorstandsvorsitz", "abteilungsleiter",
      "teamleiter", "bereichsleiter", "prokurist"],
    "Management": ["manager", "managerin", "lead", "principal", "senior manager",
      "projektleiter", "key account"],
    "Fachkraft": ["engineer", "developer", "entwickler", "consultant", "berater",
      "specialist", "spezialist", "analyst", "referent", "sachbearbeiter",
      "architect", "designer", "scientist", "expert", "associate"]
  };
  const DECISION_MAKER_LEVELS = new Set(["C-Level", "Leitung"]);
  const NON_NAME_RE = /@|http|www|tel|mobil|fax|gmbh|\bag\b|\d|straße|strasse|str\.|platz|e-mail|mail:|phone|grüße|gruesse|regards/i;
  const GRADE_RE = /\b(dr|prof|dipl|mag|ing|mba|msc|bsc|ba|ma)\.?\b/gi;

  // ---------------------------------------------------------------- Utils
  function escapeHtml(v) {
    return (v || "").replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }
  function allMatches(re, text) {
    const out = []; let m; re.lastIndex = 0;
    while ((m = re.exec(text)) !== null) { out.push(m); if (m.index === re.lastIndex) re.lastIndex++; }
    return out;
  }
  function hasCompanyHint(text) {
    const low = (text || "").toLowerCase();
    return COMPANY_HINTS.some(function (h) {
      return new RegExp("\\b" + h.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b").test(low);
    });
  }

  // -------------------------------------------------------------- HTML→Text
  function htmlToText(html) {
    if (!html) return "";
    let t = html.replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, " ");
    t = t.replace(/<\s*br\s*\/?\s*>/gi, "\n");
    t = t.replace(/<\/\s*(p|div|tr|li|h[1-6])\s*>/gi, "\n");
    t = t.replace(/<[^>]+>/g, "");
    t = t.replace(/&nbsp;/gi, " ").replace(/&amp;/gi, "&").replace(/&lt;/gi, "<")
         .replace(/&gt;/gi, ">").replace(/&quot;/gi, '"').replace(/&#39;/gi, "'")
         .replace(/&auml;/gi, "ä").replace(/&ouml;/gi, "ö").replace(/&uuml;/gi, "ü")
         .replace(/&szlig;/gi, "ß");
    const lines = t.split(/\r?\n/).map(function (l) { return l.replace(/[ \t]+/g, " ").trim(); });
    const out = []; let blank = false;
    lines.forEach(function (l) {
      if (l) { out.push(l); blank = false; } else if (!blank) { out.push(""); blank = true; }
    });
    return out.join("\n").trim();
  }

  // -------------------------------------------------------- Signaturblock
  function stripQuoted(lines) {
    const out = [];
    for (const ln of lines) {
      const low = ln.trim().toLowerCase();
      if (ln.replace(/^\s+/, "").startsWith(">")) break;
      if (/^(von|from|gesendet|sent):/.test(low) && ln.indexOf(":") >= 0) break;
      if (/^-{3,}original/.test(low) || low.startsWith("-----")) break;
      if (/^(am|on)\b.*\b(schrieb|wrote):/.test(low)) break;
      out.push(ln);
    }
    return out;
  }
  function extractSignatureBlock(body) {
    if (!body) return "";
    const lines = stripQuoted(body.split(/\r?\n/));
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].trim() === "--" || lines[i].trim() === "") {
        if (lines[i].trim() === "--") {
          const block = lines.slice(i + 1).join("\n").trim();
          if (block) return block;
        }
      }
    }
    let anchor = null;
    for (let i = 0; i < lines.length; i++) {
      const low = lines[i].trim().toLowerCase().replace(/[,.!]+$/, "").trim();
      if (GREETINGS.indexOf(low) >= 0 || GREETINGS.some(function (g) { return low.startsWith(g); })) anchor = i;
    }
    if (anchor !== null) {
      const block = lines.slice(anchor + 1).join("\n").trim();
      if (block) return block;
    }
    const nonempty = lines.filter(function (l) { return l.trim(); });
    const tail = nonempty.slice(-8).join("\n");
    if (EMAIL_RE.test(tail) || PHONE_RE.test(tail) || hasCompanyHint(tail)) return tail.trim();
    return "";
  }

  // -------------------------------------------------------- Feld-Parsing
  function classifyPhoneLine(line) {
    const low = line.toLowerCase();
    for (const field in PHONE_LABELS) {
      if (PHONE_LABELS[field].some(function (lab) { return low.indexOf(lab) >= 0; })) return field;
    }
    return null;
  }
  function detectSeniority(title) {
    const low = (title || "").toLowerCase();
    for (const level in TITLE_KEYWORDS) {
      if (TITLE_KEYWORDS[level].some(function (kw) { return low.indexOf(kw) >= 0; })) return level;
    }
    return "";
  }
  function looksLikeName(line) {
    let s = line.trim().replace(/^\|+|\|+$/g, "").trim();
    if (!s || NON_NAME_RE.test(s)) return false;
    s = s.replace(GRADE_RE, "");
    const words = s.trim().split(/[\s,]+/).filter(Boolean);
    if (!(words.length > 1 && words.length <= 4)) return false;
    const capish = words.filter(function (w) { return w[0] && w[0] === w[0].toUpperCase() && w[0] !== w[0].toLowerCase(); }).length;
    return capish >= Math.max(2, words.length - 1);
  }
  function splitName(full) {
    const cleaned = full.replace(GRADE_RE, "").trim();
    const parts = cleaned.split(/\s+/).filter(function (p) { return p && /[A-Za-zÀ-ÿ]/.test(p); });
    if (parts.length >= 2) return [parts[0], parts.slice(1).join(" ")];
    return [parts[0] || cleaned, ""];
  }
  function findCompany(lines, used) {
    for (let i = 0; i < lines.length; i++) {
      if (used.has(i)) continue;
      if (hasCompanyHint(lines[i])) {
        const chunks = lines[i].split(/\s*[|·•]\s*/);
        for (const c of chunks) if (hasCompanyHint(c)) return [c.replace(/^[\s,;|]+|[\s,;|]+$/g, ""), i];
        return [lines[i].replace(/^[\s,;|]+|[\s,;|]+$/g, ""), i];
      }
    }
    return ["", -1];
  }
  function findAddress(lines, used) {
    const street = /\b(stra(ß|ss)e|str\.|gasse|weg|platz|allee|ring|road|rd\.|street|st\.|ave)\b/i;
    const plz = /\b(\d{4,5})\s+([A-Za-zÄÖÜäöüß.\-]+)/;
    const parts = []; let location = "";
    for (let i = 0; i < lines.length; i++) {
      if (used.has(i)) continue;
      if (street.test(lines[i]) || plz.test(lines[i])) {
        parts.push(lines[i].replace(/^[\s,;|]+|[\s,;|]+$/g, ""));
        const m = lines[i].match(plz);
        if (m) location = m[2].replace(/^[.\s,-]+|[.\s,-]+$/g, "");
      }
    }
    return [parts.join(", "), location];
  }

  function parseSignature(block, fallback) {
    const sig = {
      raw_block: block || "", full_name: "", first_name: "", last_name: "",
      job_title: "", department: "", company: "", email: "", phone: "",
      mobile: "", fax: "", website: "", linkedin: "", address: "",
      seniority: "", is_decision_maker: false, location: ""
    };
    const lines = (block || "").split(/\r?\n/).map(function (l) { return l.trim(); }).filter(Boolean);
    const used = new Set();

    const em = (block || "").match(EMAIL_RE);
    if (em) sig.email = em[0].toLowerCase();
    else if (fallback && fallback.from_email) sig.email = fallback.from_email;

    const lk = (block || "").match(LINKEDIN_RE);
    if (lk) sig.linkedin = lk[0];

    const urlText = (block || "").replace(EMAIL_RE_G, " ");
    for (const um of allMatches(URL_RE_G, urlText)) {
      let cand = um[1].trim().replace(/[.,;]+$/, "");
      if (cand.indexOf("@") >= 0 || /linkedin\.com/i.test(cand)) continue;
      if (cand.indexOf(".") >= 0) { sig.website = cand; break; }
    }

    for (let i = 0; i < lines.length; i++) {
      if (!PHONE_RE.test(lines[i])) continue;
      const kind = classifyPhoneLine(lines[i]) || "phone";
      const nums = allMatches(PHONE_RE_G, lines[i]).map(function (m) { return m[1].trim(); });
      if (!nums.length) continue;
      const number = nums[0];
      if (kind === "mobile" && !sig.mobile) sig.mobile = number;
      else if (kind === "fax" && !sig.fax) sig.fax = number;
      else if (!sig.phone) sig.phone = number;
      used.add(i);
    }

    let nameIdx = -1;
    for (let i = 0; i < lines.length; i++) {
      if (used.has(i)) continue;
      if (looksLikeName(lines[i])) {
        sig.full_name = lines[i].replace(/^\|+|\|+$/g, "").trim();
        nameIdx = i; used.add(i); break;
      }
    }
    if (!sig.full_name && fallback && fallback.from_name) sig.full_name = fallback.from_name.trim();

    const comp = findCompany(lines, used);
    if (comp[0]) { sig.company = comp[0]; used.add(comp[1]); }

    let title = "";
    if (nameIdx >= 0 && nameIdx + 1 < lines.length && !used.has(nameIdx + 1)) {
      const cand = lines[nameIdx + 1];
      if (!EMAIL_RE.test(cand) && !PHONE_RE.test(cand)) { title = cand.replace(/^[\s,;|]+|[\s,;|]+$/g, ""); used.add(nameIdx + 1); }
    }
    if (!title) {
      for (let i = 0; i < lines.length; i++) {
        if (used.has(i)) continue;
        if (detectSeniority(lines[i])) { title = lines[i].split(/\s*[|·•]\s*/)[0].replace(/^[\s,;|]+|[\s,;|]+$/g, ""); used.add(i); break; }
      }
    }
    sig.job_title = title;

    for (let i = 0; i < lines.length; i++) {
      if (used.has(i)) continue;
      if (/\b(abteilung|department|team|bereich|unit)\b/i.test(lines[i])) { sig.department = lines[i].replace(/^[\s,;|]+|[\s,;|]+$/g, ""); used.add(i); break; }
    }

    const addr = findAddress(lines, used);
    sig.address = addr[0]; sig.location = addr[1];

    if (sig.full_name) { const sp = splitName(sig.full_name); sig.first_name = sp[0]; sig.last_name = sp[1]; }
    sig.seniority = detectSeniority(sig.job_title);
    sig.is_decision_maker = DECISION_MAKER_LEVELS.has(sig.seniority);
    return sig;
  }

  function extractFromEmail(mail) {
    let body = mail.text_body || "";
    let block = extractSignatureBlock(body);
    if (!block && mail.html_body) block = extractSignatureBlock(htmlToText(mail.html_body));
    if (!block) block = stripQuoted(body.split(/\r?\n/)).join("\n").trim();
    return parseSignature(block, mail);
  }

  function signatureIsEmpty(sig) {
    return !(sig.full_name || sig.job_title || sig.company || sig.phone ||
             sig.mobile || sig.email || sig.website);
  }

  // ------------------------------------------------------------- Abgleich
  const COMPARED_FIELDS = [
    ["job_title", "Position/Titel"], ["department", "Abteilung"],
    ["company", "Firma"], ["phone", "Telefon"], ["mobile", "Mobil"],
    ["website", "Website"]
  ];
  function norm(v) { return (v || "").toLowerCase().split(/\s+/).filter(Boolean).join(" "); }
  function normPhone(v) {
    if (!v) return "";
    let d = (v || "").replace(/[^\d+]/g, "");
    return d.startsWith("+") ? d : d.replace(/^0+/, "");
  }
  function valuesMatch(field, a, b) {
    if (field === "phone" || field === "mobile") {
      const na = normPhone(a), nb = normPhone(b);
      if (!na || !nb) return na === nb;
      return na === nb || na.slice(-7) === nb.slice(-7);
    }
    return norm(a) === norm(b);
  }
  function deriveSignals(sig, crm, discrepancies) {
    const signals = [];
    const changed = new Set(discrepancies.filter(function (d) { return d.change_type === "FIELD_CHANGED"; }).map(function (d) { return d.field; }));
    if (changed.has("company")) signals.push("🔁 Firmenwechsel erkannt – Kontakt prüfen (mögliche neue Opportunity bzw. Risiko beim alten Account).");
    if (changed.has("job_title")) {
      let n = "📈 Positionswechsel/Beförderung erkannt – Rolle im CRM aktualisieren.";
      if (sig.is_decision_maker) n += " Kontakt ist jetzt Entscheider:in – für Vertrieb relevant.";
      signals.push(n);
    }
    if (changed.has("phone") || changed.has("mobile")) signals.push("☎️ Geänderte Telefonnummer – Stammdaten aktualisieren.");
    if (changed.has("department")) signals.push("🏷️ Abteilung/Funktion hat sich geändert.");
    if (sig.is_decision_maker && !changed.has("job_title")) signals.push("⭐ Entscheider:in laut Signatur – Priorisierung im Vertrieb prüfen.");
    return signals;
  }
  function findCrm(crmList, email, name) {
    const e = (email || "").toLowerCase();
    if (e) { const hit = crmList.find(function (c) { return (c.email || "").toLowerCase() === e; }); if (hit) return hit; }
    const n = norm(name);
    if (n) return crmList.find(function (c) { return norm(c.full_name) === n; }) || null;
    return null;
  }
  function reconcile(sig, crmList, source) {
    const res = { source: source || "", signature: sig, crm_contact: null,
      matched: false, match_key: "", discrepancies: [], business_signals: [], notes: [] };
    const crm = findCrm(crmList, sig.email, sig.full_name);
    if (!crm) {
      COMPARED_FIELDS.forEach(function (f) {
        const v = sig[f[0]]; if (v) res.discrepancies.push({ field: f[0], change_type: "FIELD_NEW_IN_CRM", signature_value: v, crm_value: "" });
      });
      res.business_signals.push("🆕 Kontakt nicht im CRM gefunden – als neuen Lead/Kontakt anlegen.");
      if (sig.is_decision_maker) res.business_signals.push("⭐ Neuer Kontakt ist laut Signatur Entscheider:in.");
      res.notes.push("Kein CRM-Treffer für E-Mail '" + (sig.email || "—") + "' / Name '" + (sig.full_name || "—") + "'.");
      return res;
    }
    res.matched = true; res.crm_contact = crm;
    res.match_key = (sig.email && sig.email === (crm.email || "").toLowerCase()) ? "email" : "name";
    COMPARED_FIELDS.forEach(function (f) {
      const field = f[0]; const sv = sig[field] || ""; const cv = crm[field] || "";
      if (!sv) return;
      if (!cv) res.discrepancies.push({ field: field, change_type: "FIELD_NEW_IN_CRM", signature_value: sv, crm_value: "" });
      else if (valuesMatch(field, sv, cv)) res.discrepancies.push({ field: field, change_type: "MATCH", signature_value: sv, crm_value: cv });
      else res.discrepancies.push({ field: field, change_type: "FIELD_CHANGED", signature_value: sv, crm_value: cv });
    });
    res.business_signals = deriveSignals(sig, crm, res.discrepancies);
    return res;
  }
  function hasActionableChanges(res) {
    return (!res.matched) || res.discrepancies.some(function (d) {
      return d.change_type === "FIELD_CHANGED" || d.change_type === "FIELD_NEW_IN_CRM";
    });
  }
  function tone(res) { return !res.matched ? "new" : (hasActionableChanges(res) ? "upd" : "ok"); }

  // --------------------------------------------------------------- .eml
  function decodeBytes(bytes, charset) {
    const cs = (charset || "utf-8").toLowerCase().replace("utf8", "utf-8");
    try { return new TextDecoder(cs).decode(bytes); }
    catch (e) { try { return new TextDecoder("utf-8").decode(bytes); } catch (e2) { return String.fromCharCode.apply(null, bytes); } }
  }
  function b64ToBytes(s) {
    const clean = (s || "").replace(/[^A-Za-z0-9+/=]/g, "");
    const bin = (typeof atob === "function") ? atob(clean) : Buffer.from(clean, "base64").toString("binary");
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  function qpToBytes(s) {
    s = s.replace(/=\r?\n/g, "");
    const out = [];
    for (let i = 0; i < s.length; i++) {
      if (s[i] === "=" && i + 2 < s.length) { out.push(parseInt(s.substr(i + 1, 2), 16)); i += 2; }
      else out.push(s.charCodeAt(i));
    }
    return new Uint8Array(out);
  }
  function decodeRFC2047(value) {
    if (!value || value.indexOf("=?") < 0) return value || "";
    return value.replace(/=\?([^?]+)\?([bBqQ])\?([^?]*)\?=/g, function (_, cs, enc, txt) {
      let bytes;
      if (enc.toUpperCase() === "B") bytes = b64ToBytes(txt);
      else bytes = qpToBytes(txt.replace(/_/g, " "));
      return decodeBytes(bytes, cs);
    });
  }
  function parseHeaders(headerText) {
    const headers = {}; const lines = headerText.split(/\r?\n/); let cur = null;
    for (const ln of lines) {
      if (/^[ \t]/.test(ln) && cur) { headers[cur] += " " + ln.trim(); continue; }
      const idx = ln.indexOf(":");
      if (idx > 0) { cur = ln.slice(0, idx).trim().toLowerCase(); headers[cur] = ln.slice(idx + 1).trim(); }
    }
    return headers;
  }
  function getBoundary(ct) { const m = (ct || "").match(/boundary="?([^";]+)"?/i); return m ? m[1] : ""; }
  function getCharset(ct) { const m = (ct || "").match(/charset="?([^";]+)"?/i); return m ? m[1] : "utf-8"; }

  function decodePart(rawBody, headers) {
    const cte = (headers["content-transfer-encoding"] || "7bit").toLowerCase();
    const charset = getCharset(headers["content-type"]);
    let bytes;
    if (cte.indexOf("base64") >= 0) bytes = b64ToBytes(rawBody);
    else if (cte.indexOf("quoted-printable") >= 0) bytes = qpToBytes(rawBody);
    else return rawBody;
    return decodeBytes(bytes, charset);
  }

  function walkParts(rawBody, headers, acc) {
    const ct = headers["content-type"] || "text/plain";
    if (/multipart\//i.test(ct)) {
      const boundary = getBoundary(ct);
      if (!boundary) return;
      const segs = rawBody.split("--" + boundary);
      for (let seg of segs) {
        seg = seg.replace(/^\r?\n/, "");
        if (!seg || seg.startsWith("--")) continue;
        const sp = seg.indexOf("\r\n\r\n") >= 0 ? seg.indexOf("\r\n\r\n") : seg.indexOf("\n\n");
        if (sp < 0) continue;
        const hsep = seg.indexOf("\r\n\r\n") >= 0 ? 4 : 2;
        const ph = parseHeaders(seg.slice(0, sp));
        const pb = seg.slice(sp + hsep);
        walkParts(pb, ph, acc);
      }
    } else if (/text\/plain/i.test(ct)) {
      if (!acc.text) acc.text = decodePart(rawBody, headers);
    } else if (/text\/html/i.test(ct)) {
      if (!acc.html) acc.html = decodePart(rawBody, headers);
    }
  }

  function parseAddr(value) {
    if (!value) return ["", ""];
    const m = value.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/);
    if (m) return [m[1].trim(), m[2].trim()];
    if (value.indexOf("@") >= 0) return ["", value.trim()];
    return [value.trim(), ""];
  }

  function parseEml(raw, source) {
    raw = raw.replace(/\r\n/g, "\n");
    const sep = raw.indexOf("\n\n");
    const headerText = sep >= 0 ? raw.slice(0, sep) : raw;
    const bodyRaw = (sep >= 0 ? raw.slice(sep + 2) : "").replace(/\n/g, "\r\n");
    const headers = parseHeaders(headerText);
    const fromParsed = parseAddr(decodeRFC2047(headers["from"] || ""));
    const acc = {};
    walkParts(bodyRaw, headers, acc);
    let text = acc.text || ""; let html = acc.html || "";
    if (!text && !html) {
      if (/text\/html/i.test(headers["content-type"] || "")) html = decodePart(bodyRaw, headers);
      else text = decodePart(bodyRaw, headers);
    }
    if (!text && html) text = htmlToText(html);
    return {
      source: source || "", from_name: fromParsed[0] || "",
      from_email: (fromParsed[1] || "").toLowerCase(),
      subject: decodeRFC2047(headers["subject"] || ""),
      date: headers["date"] || "", text_body: text || "", html_body: html || ""
    };
  }

  // --------------------------------------------------------------- .msg (OLE/CFB)
  const ENDOFCHAIN = 0xFFFFFFFE, FREESECT = 0xFFFFFFFF;
  function parseMsg(uint8, source) {
    const dv = new DataView(uint8.buffer, uint8.byteOffset, uint8.byteLength);
    const sig = [0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1];
    for (let i = 0; i < 8; i++) if (uint8[i] !== sig[i]) throw new Error("Keine gültige .msg/OLE-Datei");
    const sectorSize = 1 << dv.getUint16(30, true);
    const miniSize = 1 << dv.getUint16(32, true);
    const numFat = dv.getUint32(44, true);
    const firstDir = dv.getUint32(48, true);
    const miniCutoff = dv.getUint32(56, true);
    const firstMiniFat = dv.getUint32(60, true);
    const numMiniFat = dv.getUint32(64, true);
    let firstDifat = dv.getUint32(68, true);
    const numDifat = dv.getUint32(72, true);
    const u32 = function (off) { return dv.getUint32(off, true); };
    const secOff = function (s) { return (s + 1) * sectorSize; };

    // DIFAT -> Liste der FAT-Sektoren
    const fatSectors = [];
    for (let i = 0; i < 109; i++) { const v = u32(76 + i * 4); if (v !== FREESECT && v !== ENDOFCHAIN) fatSectors.push(v); }
    let ds = firstDifat, guard = 0;
    while (ds !== ENDOFCHAIN && ds !== FREESECT && guard++ < 100000) {
      const base = secOff(ds); const per = sectorSize / 4 - 1;
      for (let i = 0; i < per; i++) { const v = u32(base + i * 4); if (v !== FREESECT && v !== ENDOFCHAIN) fatSectors.push(v); }
      ds = u32(base + per * 4);
    }
    // FAT
    const fat = [];
    fatSectors.forEach(function (fs) { const base = secOff(fs); for (let i = 0; i < sectorSize / 4; i++) fat.push(u32(base + i * 4)); });

    function readChain(start, sizeLimit) {
      const parts = []; let s = start, total = 0, guard = 0;
      while (s !== ENDOFCHAIN && s !== FREESECT && guard++ < 10000000) {
        const off = secOff(s);
        parts.push(uint8.subarray(off, off + sectorSize)); total += sectorSize;
        s = fat[s]; if (s === undefined) break;
        if (sizeLimit && total >= sizeLimit) break;
      }
      const out = new Uint8Array(total); let p = 0;
      parts.forEach(function (a) { out.set(a, p); p += a.length; });
      return sizeLimit ? out.subarray(0, sizeLimit) : out;
    }

    // Directory
    const dirBytes = readChain(firstDir);
    const ddv = new DataView(dirBytes.buffer, dirBytes.byteOffset, dirBytes.byteLength);
    const entries = [];
    for (let off = 0; off + 128 <= dirBytes.length; off += 128) {
      const nameLen = ddv.getUint16(off + 64, true);
      const objType = dirBytes[off + 66];
      if (objType === 0) continue;
      let name = "";
      if (nameLen > 2) name = new TextDecoder("utf-16le").decode(dirBytes.subarray(off, off + nameLen - 2));
      entries.push({ name: name, objType: objType, start: ddv.getUint32(off + 116, true), size: ddv.getUint32(off + 120, true) });
    }
    const root = entries.find(function (e) { return e.objType === 5; });
    const miniStream = root ? readChain(root.start, root.size) : new Uint8Array(0);
    // Mini-FAT
    const miniFat = [];
    if (firstMiniFat !== ENDOFCHAIN) {
      const mfb = readChain(firstMiniFat);
      const mdv = new DataView(mfb.buffer, mfb.byteOffset, mfb.byteLength);
      for (let i = 0; i + 4 <= mfb.length; i += 4) miniFat.push(mdv.getUint32(i, true));
    }
    function readMini(start, size) {
      const parts = []; let s = start, total = 0, guard = 0;
      while (s !== ENDOFCHAIN && s !== FREESECT && guard++ < 10000000) {
        const off = s * miniSize; parts.push(miniStream.subarray(off, off + miniSize)); total += miniSize;
        s = miniFat[s]; if (s === undefined) break;
      }
      const out = new Uint8Array(total); let p = 0; parts.forEach(function (a) { out.set(a, p); p += a.length; });
      return out.subarray(0, size);
    }
    function streamData(entry) {
      if (entry.size >= miniCutoff) return readChain(entry.start, entry.size);
      return readMini(entry.start, entry.size);
    }
    const streams = {};
    entries.forEach(function (e) { if (e.objType === 2 && e.name.indexOf("__substg1.0_") === 0) streams[e.name.split("_").pop().toUpperCase()] = streamData(e); });

    function getStr(pid) {
      let d = streams[pid + "001F"]; if (d) return new TextDecoder("utf-16le").decode(d);
      d = streams[pid + "001E"]; if (d) return decodeBytes(d, "cp1252"); return "";
    }
    const subject = getStr("0037");
    const body = getStr("1000");
    let html = "";
    const hb = streams["10130102"];
    if (hb) html = decodeBytes(hb, "utf-8");
    const headers = getStr("007D");
    let fromName = getStr("0C1A"), fromEmail = "";
    ["5D01", "0C1F", "5D02", "0065"].some(function (pid) { const v = getStr(pid); if (v.indexOf("@") >= 0) { fromEmail = v; return true; } return false; });
    let date = "";
    if (headers) {
      const h = parseHeaders(headers.replace(/\r\n/g, "\n"));
      date = h["date"] || "";
      const fp = parseAddr(decodeRFC2047(h["from"] || ""));
      if (fp[1]) { fromName = fp[0] || fromName; fromEmail = fp[1]; }
    }
    let text = body;
    if (!text && html) text = htmlToText(html);
    return {
      source: source || "", from_name: (fromName || "").trim(),
      from_email: (fromEmail || "").trim().toLowerCase(), subject: (subject || "").trim(),
      date: date, text_body: text || "", html_body: html || ""
    };
  }

  // --------------------------------------------------------------- API
  function analyze(loaded, crmList) {
    const sig = extractFromEmail(loaded);
    if (signatureIsEmpty(sig)) return { skipped: true, source: loaded.source, reason: "Keine verwertbare Signatur gefunden." };
    const res = reconcile(sig, crmList, loaded.source);
    res.tone = tone(res);
    res.has_actionable = hasActionableChanges(res);
    return res;
  }

  const API = {
    parseEml: parseEml, parseMsg: parseMsg, htmlToText: htmlToText,
    extractSignatureBlock: extractSignatureBlock, parseSignature: parseSignature,
    extractFromEmail: extractFromEmail, reconcile: reconcile, analyze: analyze,
    tone: tone, hasActionableChanges: hasActionableChanges, escapeHtml: escapeHtml,
    signatureIsEmpty: signatureIsEmpty, splitName: splitName
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  root.SignaturCore = API;
})(typeof window !== "undefined" ? window : globalThis);
