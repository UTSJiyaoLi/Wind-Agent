const fs = require("fs");
const zlib = require("zlib");
const path = process.argv[2];
const b64 = process.argv[3];
const inflated = zlib.inflateRawSync(Buffer.from(b64, 'base64')).toString('utf8');
const xml = decodeURIComponent(inflated);
fs.writeFileSync(path + '.inner.xml', xml, 'utf8');
