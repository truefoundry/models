import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const FIXTURES_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../fixtures');

function readBase64(name: string): string {
  return fs.readFileSync(path.join(FIXTURES_DIR, name)).toString('base64');
}

let pngDataUrl: string | undefined;
let pdfFileData: string | undefined;

/** data:image/png;base64,… from fixtures/sample-image-with-text.png */
export function sampleImageDataUrl(): string {
  if (!pngDataUrl) {
    pngDataUrl = `data:image/png;base64,${readBase64('sample-image-with-text.png')}`;
  }
  return pngDataUrl;
}

/** Raw base64 of fixtures/sample.pdf (for OpenAI-style file.file_data). */
export function samplePdfBase64(): string {
  if (!pdfFileData) pdfFileData = readBase64('sample.pdf');
  return pdfFileData;
}
