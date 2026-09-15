import assert from 'node:assert/strict';
import { canonicalize, hashConfigData } from './versionFile';

const first = {
  provider: {
    models: {
      'model-b': { z: 2, a: 1 },
      'model-a': { nested: { y: 2, x: 1 } },
    },
    enabled: true,
  },
  version: 1,
};

const sameDataWithDifferentKeyOrder = {
  version: 1,
  provider: {
    enabled: true,
    models: {
      'model-a': { nested: { x: 1, y: 2 } },
      'model-b': { a: 1, z: 2 },
    },
  },
};

assert.deepEqual(canonicalize(first), canonicalize(sameDataWithDifferentKeyOrder));
assert.equal(hashConfigData(first), hashConfigData(sameDataWithDifferentKeyOrder));
assert.notEqual(hashConfigData([1, 2]), hashConfigData([2, 1]));

console.log('versionFile canonicalization tests passed');
