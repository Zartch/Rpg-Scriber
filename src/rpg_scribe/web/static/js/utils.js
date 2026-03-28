/* RPG Scribe - pure utility functions */

export function escapeHtml(str) {
  var div = document.createElement("div");
  div.appendChild(document.createTextNode(str || ""));
  return div.innerHTML;
}

export function escapeAttr(str) {
  return (str || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function formatTime(ts) {
  if (!ts) return "";
  var d = new Date(ts * 1000);
  return d.toLocaleTimeString();
}

export function formatDate(ts) {
  if (!ts) return "";
  var d = new Date(ts * 1000);
  return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function formatDuration(minutes) {
  if (!minutes && minutes !== 0) return "";
  if (minutes < 60) return Math.round(minutes) + " min";
  var h = Math.floor(minutes / 60);
  var m = Math.round(minutes % 60);
  return h + "h " + (m > 0 ? m + "m" : "");
}

export function locationName(loc) {
  if (!loc) return "";
  if (typeof loc === "string") return loc.trim();
  if (typeof loc === "object") return String(loc.name || "").trim();
  return String(loc).trim();
}

export function locationDescription(loc) {
  if (loc && typeof loc === "object") return String(loc.description || "").trim();
  return "";
}

export function entityType(entity) {
  if (entity && typeof entity === "object") return String(entity.entity_type || "group").trim() || "group";
  return "group";
}

export function entityDescription(entity) {
  if (entity && typeof entity === "object") return String(entity.description || "").trim();
  return "";
}

export function formatLatency(seconds) {
  if (seconds < 1) return Math.round(seconds * 1000) + "ms";
  return seconds.toFixed(1) + "s";
}

export function latencyClass(seconds) {
  if (seconds < 2) return "latency-good";
  if (seconds < 10) return "latency-ok";
  return "latency-slow";
}

export function createSpinner() {
  var el = document.createElement("span");
  el.className = "spinner-inline";
  el.setAttribute("aria-hidden", "true");
  return el;
}

export function withLoading(btn, asyncFn, options) {
  options = options || {};
  var originalHTML = btn.innerHTML;
  var originalDisabled = btn.disabled;

  btn.disabled = true;
  btn.innerHTML = "";
  btn.appendChild(createSpinner());
  btn.appendChild(document.createTextNode(options.loadingText || "Loading..."));

  var promise = asyncFn();

  promise.finally(function() {
    btn.disabled = originalDisabled;
    btn.innerHTML = originalHTML;
  });

  return promise;
}

export function withPanelLoading(container, asyncFn) {
  // Ensure container has relative positioning
  if (!container.classList.contains('panel-loadable')) {
    container.classList.add('panel-loadable');
  }

  // Create overlay
  var overlay = document.createElement('div');
  overlay.className = 'loading-overlay';
  var spinner = document.createElement('div');
  spinner.className = 'spinner';
  overlay.appendChild(spinner);
  container.appendChild(overlay);

  var promise = asyncFn();

  promise.finally(function() {
    if (overlay.parentNode) {
      overlay.parentNode.removeChild(overlay);
    }
  });

  return promise;
}

export function showSkeleton(container, lineCount) {
  lineCount = lineCount || 3;
  // Store original content if not already stored
  if (!container.dataset.preSkeletonContent) {
    container.dataset.preSkeletonContent = container.innerHTML;
  }

  var skeletonHTML = "";
  for (var i = 0; i < lineCount; i++) {
    skeletonHTML += '<div class="skeleton-line"></div>';
  }
  container.innerHTML = skeletonHTML;
}

export function hideSkeleton(container) {
  // Remove skeleton elements
  var skeletonElements = container.querySelectorAll('.skeleton-line, .skeleton-block');
  for (var i = 0; i < skeletonElements.length; i++) {
    skeletonElements[i].remove();
  }

  // Restore original content if available
  if (container.dataset.preSkeletonContent) {
    container.innerHTML = container.dataset.preSkeletonContent;
    delete container.dataset.preSkeletonContent;
  }
}

export function setRefreshing(container, active) {
  if (active) {
    container.classList.add('content-refreshing');
  } else {
    container.classList.remove('content-refreshing');
  }
}
