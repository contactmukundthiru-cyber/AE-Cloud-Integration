const fs = require('fs');
const path = require('path');
const archiver = require('archiver');

const distDir = path.resolve(__dirname, '..', 'dist');
const outPath = path.resolve(__dirname, '..', 'cloudexport.uxp');

if (!fs.existsSync(distDir)) {
  throw new Error('dist directory not found. Run npm run build first.');
}

const output = fs.createWriteStream(outPath);
const archive = archiver('zip', { zlib: { level: 9 } });

output.on('close', () => {
  console.log(`Created ${outPath} (${archive.pointer()} bytes)`);
});

archive.on('error', (err) => {
  throw err;
});

archive.pipe(output);
archive.directory(distDir, false);
archive.finalize();
