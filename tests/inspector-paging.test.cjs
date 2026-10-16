const test = require('node:test');
const assert = require('node:assert/strict');
const ui = require('../oopc/web/app.js');
test('neighborhood cursor keys bind entity and exact filters, independent of property order', () => {
  assert.equal(ui.neighborhoodPageKey('polymer', {environment:'wet',status:'seed'}), ui.neighborhoodPageKey('polymer', {status:'seed',environment:'wet'}));
  assert.notEqual(ui.neighborhoodPageKey('polymer', {environment:'wet'}), ui.neighborhoodPageKey('polymer', {environment:'dry'}));
  assert.notEqual(ui.neighborhoodPageKey('polymer', {}), ui.neighborhoodPageKey('other', {}));
});
test('imported failures and active checkpoints never masquerade as completed live tasks', () => {
  assert.equal(ui.runStatusLabel({imported:true,status:'failed',recorded_status:'failed'}), 'Replay · recorded failed');
  assert.equal(ui.runStatusLabel({imported:true,status:'checkpoint',recorded_status:'running'}), 'Replay · recorded running');
  assert.match(ui.runStatusLabel({imported:true,status:'completed'}), /unknown/);
  assert.match(ui.replayStatusNote({imported:true,status:'completed'}), /cannot be inferred/);
  assert.equal(ui.isReplaySnapshot({imported:true}), true);
  assert.equal(ui.isReplaySnapshot({status:'running'}), false);
});
