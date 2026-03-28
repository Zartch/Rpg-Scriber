/* RPG Scribe - API helper functions */

export async function apiGet(path) {
  var res = await fetch(path);
  if (!res.ok) throw new Error("GET " + path + " failed: " + res.status);
  return res.json();
}

export async function apiPost(path, body) {
  var res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("POST " + path + " failed: " + res.status);
  return res.json();
}

export async function apiPut(path, body) {
  var res = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("PUT " + path + " failed: " + res.status);
  return res.json();
}

export async function apiPatch(path, body) {
  var res = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("PATCH " + path + " failed: " + res.status);
  return res.json();
}

export async function apiDelete(path) {
  var res = await fetch(path, { method: "DELETE" });
  if (!res.ok) throw new Error("DELETE " + path + " failed: " + res.status);
  return res.json();
}

export async function apiPostRaw(path, body) {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
