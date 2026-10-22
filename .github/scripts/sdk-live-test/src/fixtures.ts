import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const FIXTURES_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../fixtures');

function readBytes(name: string): Buffer {
  return fs.readFileSync(path.join(FIXTURES_DIR, name));
}

function readBase64(name: string): string {
  return readBytes(name).toString('base64');
}

let pngDataUrl: string | undefined;
let pdfFileData: string | undefined;
let wavBytes: Uint8Array | undefined;
let wavB64: string | undefined;

/** data:image/png;base64,… for chat vision / embedding image. */
export function sampleImageDataUrl(): string {
  if (!pngDataUrl) {
    pngDataUrl = `data:image/png;base64,${readBase64('sample-image-with-text.png')}`;
  }
  return pngDataUrl;
}

/** Raw base64 of sample.pdf for OpenAI-style file.file_data. */
export function samplePdfBase64(): string {
  if (!pdfFileData) pdfFileData = readBase64('sample.pdf');
  return pdfFileData;
}

/** Spoken pangram WAV (fixtures/sample.wav) for transcription / chat audio. */
export function sampleWavBytes(): Uint8Array {
  if (!wavBytes) wavBytes = new Uint8Array(readBytes('sample.wav'));
  return wavBytes;
}

export function sampleWavBase64(): string {
  if (!wavB64) wavB64 = Buffer.from(sampleWavBytes()).toString('base64');
  return wavB64;
}
