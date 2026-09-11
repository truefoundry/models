import crypto from "crypto";
import fs from "fs";

/** Opaque version metadata published alongside a generated config file. */
export interface ConfigVersionMetadata {
  hash: string;
  datetime: string;
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
  const canonicalJson = JSON.stringify(data);
  const hash = crypto.createHash("sha256").update(canonicalJson).digest("hex");
  const metadata: ConfigVersionMetadata = {
    hash,
    datetime: new Date().toISOString(),
  };

  fs.writeFileSync(
    versionOutputFile,
    JSON.stringify(metadata, null, 2),
    "utf-8",
  );

  console.log(
    `Wrote ${label} version metadata to ${versionOutputFile}: ${hash}`,
  );
}
