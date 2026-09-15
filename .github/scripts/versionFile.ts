import crypto from "crypto";
import fs from "fs";

/** Opaque version metadata published alongside a generated config file. */
export interface ConfigVersionMetadata {
  hash: string;
  datetime: string;
}

export function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }

  if (value !== null && typeof value === "object") {
    const objectValue = value as Record<string, unknown>;
    return Object.keys(objectValue)
      .sort()
      .reduce<Record<string, unknown>>((canonicalObject, key) => {
        canonicalObject[key] = canonicalize(objectValue[key]);
        return canonicalObject;
      }, {});
  }

  return value;
}

export function hashConfigData(data: unknown): string {
  const canonicalJson = JSON.stringify(canonicalize(data));
  return crypto.createHash("sha256").update(canonicalJson).digest("hex");
}

export function createVersionMetadata(data: unknown, datetime = new Date().toISOString()): ConfigVersionMetadata {
  return {
    hash: hashConfigData(data),
    datetime,
  };
}

/**
 * Writes version metadata (hash of `data`'s canonical JSON + current UTC datetime) to
 * `versionOutputFile`. Consumers (servicefoundry-server, tfy-k8s-controller) treat the hash
 * as opaque and never recompute it — this is the single source of truth for both fields.
 */
export function writeVersionFile(
  versionOutputFile: string,
  data: unknown,
  label: string,
): void {
  const metadata = createVersionMetadata(data);

  fs.writeFileSync(
    versionOutputFile,
    JSON.stringify(metadata, null, 2),
    "utf-8",
  );

  console.log(
    `Wrote ${label} version metadata to ${versionOutputFile}: ${metadata.hash}`,
  );
}
