const fs = require("fs");
const zlib = require("zlib");
const path = `C:/wind-agent/docs/diagrams/wind-agent-agent-workflow.drawio`;
const xml = fs.readFileSync(path, 'utf8');
const m = xml.match(/<diagram[^>]*>([\s\S]*?)<\/diagram>/);
if (!m) throw new Error('No diagram content');
const inner = m[1].trim();
if (!inner.startsWith('<mxGraphModel')) {
  console.log('already encoded or unexpected');
  process.exit(0);
}
const encoded = encodeURIComponent(inner).replace(/%20/g, ' ');
const compressed = zlib.deflateRawSync(Buffer.from(encoded, 'utf8')).toString('base64');
const out = xml.replace(/<diagram([^>]*)>[\s\S]*?<\/diagram>/, `<diagram$1>${compressed}</diagram>`);
fs.writeFileSync(path, out, 'utf8');
console.log('converted');
