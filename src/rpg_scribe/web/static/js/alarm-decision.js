/* RPG Scribe - alarma de transcripción: lógica de decisión pura (sin DOM/audio) */

export var TRANSCRIPTION_TIMEOUT_MS = 120000;
export var WS_GRACE_MS = 20000;
export var CHECK_INTERVAL_MS = 5000;

// state = { armed, wsConnected, wsDownSince, lastTranscriptionAt }
// Devuelve { shouldAlarm, reason, silentSeconds }.
export function evaluateAlarm(state, now) {
  if (!state.armed) {
    return { shouldAlarm: false, reason: null, silentSeconds: 0 };
  }

  // Servidor muerto/congelado: el WebSocket se cae. Toleramos un margen para
  // reconexiones transitorias.
  if (!state.wsConnected) {
    if (state.wsDownSince != null && now - state.wsDownSince > WS_GRACE_MS) {
      return {
        shouldAlarm: true,
        reason: "ws-down",
        silentSeconds: Math.floor((now - state.wsDownSince) / 1000),
      };
    }
    return { shouldAlarm: false, reason: null, silentSeconds: 0 };
  }

  // WS vivo: audio degradado = llegan cosas pero no transcripciones.
  if (
    state.lastTranscriptionAt != null &&
    now - state.lastTranscriptionAt > TRANSCRIPTION_TIMEOUT_MS
  ) {
    return {
      shouldAlarm: true,
      reason: "transcription-timeout",
      silentSeconds: Math.floor((now - state.lastTranscriptionAt) / 1000),
    };
  }

  return { shouldAlarm: false, reason: null, silentSeconds: 0 };
}

export function formatBannerMessage(reason, silentSeconds) {
  if (reason === "ws-down") {
    return (
      "⚠️ Conexión con el servidor perdida hace " +
      silentSeconds +
      "s — la transcripción puede estar detenida. Revisa el bot."
    );
  }
  return (
    "⚠️ Sin transcripción desde hace " +
    silentSeconds +
    "s — revisa el bot."
  );
}
