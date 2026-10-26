import assert from 'node:assert/strict';
import {test} from 'node:test';
import {groupHarnessVersions, harnessChoices} from '../site/harness-versions.js';

const h = (version, state = 'ready', family = 'unica') => ({id: `${family}-${version}`, family, version, state});

test('the default offers the newest release per harness, not the first installed one', () => {
  const items = [h('0.13.0'), h('0.15.0-rc.1', 'absent'), h('0.14.0-rc.1'), h('1.0.0', 'ready', 'other')];
  assert.deepEqual(harnessChoices(items, false).map(x => x.id), ['unica-0.15.0-rc.1', 'other-1.0.0']);
  assert.deepEqual(items.map(x => x.version), ['0.13.0', '0.15.0-rc.1', '0.14.0-rc.1', '1.0.0']);
  assert.equal(harnessChoices(items, true).length, 4);
});

test('numeric versions and prerelease precedence determine the latest version', () => {
  const items = ['1.9.0', '1.10.0-rc.2', '1.10.0-rc.10', '1.10.0', '1.10.0-beta.1'].map(v => h(v));
  const group = groupHarnessVersions(items)[0];
  assert.equal(group.latest.version, '1.10.0');
  assert.deepEqual(group.older.map(x => x.version), ['1.10.0-rc.10', '1.10.0-rc.2', '1.10.0-beta.1', '1.9.0']);
});

test('hiding old versions preserves the explicitly chosen exam environment', () => {
  const items = [h('0.13.0'), h('0.14.0-rc.1'), h('0.15.0-rc.1')];
  assert.deepEqual(harnessChoices(items, false, 'unica-0.13.0').map(x => x.version), ['0.15.0-rc.1', '0.13.0']);
});

test('an unsupported latest release does not make an older version appear current', () => {
  const items = [h('0.13.0'), h('0.15.0-rc.1', 'unavailable')];
  assert.equal(groupHarnessVersions(items)[0].latest.state, 'unavailable');
  assert.equal(harnessChoices(items, true)[1].version, '0.13.0');
});

test('unversioned custom harnesses remain independent', () => {
  const items = [{id: 'custom', label: 'Custom'}, {id: 'skills', version: 'a1b2c3'}];
  assert.deepEqual(harnessChoices(items, false), items);
});
