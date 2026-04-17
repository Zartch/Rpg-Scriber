/* RPG Scribe - WebSocket connection */

import { state } from "./state.js";

var ws = null;
var reconnectDelay = 1000;
var MAX_RECONNECT = 16000;

var handlers = {};

export function registerHandler(type, fn) {
  handlers[type] = fn;
}

export function connectWS() {
  var proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(proto + "//" + location.host + "/ws/live");

  ws.onopen = function () {
    reconnectDelay = 1000;
    var connectionBadge = document.getElementById("connection-badge");
    if (connectionBadge) {
      connectionBadge.textContent = "Connected";
      connectionBadge.className = "badge badge-connected";
    }
  };

  ws.onclose = function () {
    var connectionBadge = document.getElementById("connection-badge");
    if (connectionBadge) {
      connectionBadge.textContent = "Disconnected";
      connectionBadge.className = "badge badge-idle";
    }
    setTimeout(connectWS, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT);
  };

  ws.onerror = function () {
    ws.close();
  };

  ws.onmessage = function (evt) {
    if (state.appMode !== "live" || state.viewingHistorical) return; // ignore live updates outside live mode
    var msg;
    try { msg = JSON.parse(evt.data); } catch (_) { return; }
    handleMessage(msg);
  };
}

function handleMessage(msg) {
  if (handlers[msg.type]) {
    handlers[msg.type](msg.data);
  }
}
