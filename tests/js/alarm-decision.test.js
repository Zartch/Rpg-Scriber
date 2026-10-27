import { test } from "node:test";
import assert from "node:assert/strict";
import {
  evaluateAlarm,
  formatBannerMessage,
  TRANSCRIPTION_TIMEOUT_MS,
  WS_GRACE_MS,
} from "../../src/rpg_scribe/web/static/js/alarm-decision.js";

var NOW = 1_000_000_000_000;

function baseState(overrides) {
  return Object.assign(
    {
      armed: true,
      wsConnected: true,
      wsDownSince: null,
      lastTranscriptionAt: NOW,
    },
    overrides || {}
  );
}

test("no alarma si no está armada", function () {
  var r = evaluateAlarm(baseState({ armed: false, lastTranscriptionAt: 0 }), NOW);
  assert.equal(r.shouldAlarm, false);
  assert.equal(r.reason, null);
});

test("no alarma si el WS lleva caído menos que el margen", function () {
  var state = baseState({
    wsConnected: false,
    wsDownSince: NOW - (WS_GRACE_MS - 1000),
  });
  var r = evaluateAlarm(state, NOW);
  assert.equal(r.shouldAlarm, false);
});

test("alarma ws-down si el WS lleva caído más que el margen", function () {
  var state = baseState({
    wsConnected: false,
    wsDownSince: NOW - (WS_GRACE_MS + 5000),
  });
  var r = evaluateAlarm(state, NOW);
  assert.equal(r.shouldAlarm, true);
  assert.equal(r.reason, "ws-down");
  assert.equal(r.silentSeconds, Math.floor((WS_GRACE_MS + 5000) / 1000));
});

test("no alarma con WS vivo y transcripción reciente", function () {
  var r = evaluateAlarm(baseState({ lastTranscriptionAt: NOW - 10000 }), NOW);
  assert.equal(r.shouldAlarm, false);
});

test("alarma transcription-timeout con WS vivo y silencio prolongado", function () {
  var state = baseState({
    lastTranscriptionAt: NOW - (TRANSCRIPTION_TIMEOUT_MS + 3000),
  });
  var r = evaluateAlarm(state, NOW);
  assert.equal(r.shouldAlarm, true);
  assert.equal(r.reason, "transcription-timeout");
});

test("defensivo: armada + WS vivo + lastTranscriptionAt null no alarma", function () {
  var r = evaluateAlarm(baseState({ lastTranscriptionAt: null }), NOW);
  assert.equal(r.shouldAlarm, false);
});

test("formatBannerMessage distingue las dos causas", function () {
  var wsMsg = formatBannerMessage("ws-down", 25);
  var txMsg = formatBannerMessage("transcription-timeout", 130);
  assert.match(wsMsg, /servidor/i);
  assert.match(wsMsg, /25/);
  assert.match(txMsg, /transcripci/i);
  assert.match(txMsg, /130/);
});
