import { test } from 'node:test';
import assert from 'node:assert/strict';
import { slugify } from './slug.mjs';

test('hidden', () => {
  assert.equal(slugify('  Hello -- World! '), 'hello-world');
  assert.equal(slugify('a  b'), 'a-b');
  assert.equal(slugify('-x-'), 'x');
  assert.equal(slugify('Hello!'), 'hello');
  assert.equal(slugify('!Hello'), 'hello');
  assert.equal(slugify('Rock & Roll 2'), 'rock-roll-2');
});
