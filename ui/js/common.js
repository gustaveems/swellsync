/*
 * Shared browser helpers. Every call goes straight from the browser to a
 * service; the base URLs come from config.js. No framework, no build step.
 */
(function () {
  "use strict";

  var cfg = window.SWELLSYNC_CONFIG || {};

  // Resolves to { status, data }. A network failure resolves to status 0 with
  // a readable message, so pages can show a degraded state instead of hanging.
  function api(base, path, options) {
    options = options || {};
    var init = { method: options.method || "GET", headers: {} };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    var url = base + path;
    return fetch(url, init)
      .then(function (res) {
        if (res.status === 204) return { status: 204, data: null };
        return res.json()
          .catch(function () { return {}; })
          .then(function (data) { return { status: res.status, data: data }; });
      })
      .catch(function () {
        return { status: 0, data: { error: "Could not reach " + base + ". Is the service running?" } };
      });
  }

  function flash(message, kind) {
    var box = document.getElementById("flash");
    if (!box) return;
    box.innerHTML = "";
    var node = document.createElement("div");
    node.className = "flash flash-" + (kind || "success");
    node.textContent = message;
    box.appendChild(node);
  }

  // Builds an element without innerHTML, so stored text can never run as markup.
  function el(tag, props, children) {
    var node = document.createElement(tag);
    Object.keys(props || {}).forEach(function (key) {
      if (key === "text") node.textContent = props[key];
      else if (key === "className") node.className = props[key];
      else node.setAttribute(key, props[key]);
    });
    (children || []).forEach(function (child) {
      if (child) node.appendChild(child);
    });
    return node;
  }

  function errorText(result, fallback) {
    var data = result.data || {};
    if (data.errors) {
      return Object.keys(data.errors).map(function (field) {
        return field.replace(/_/g, " ") + ": " + data.errors[field];
      }).join(" · ");
    }
    return data.error || fallback;
  }

  window.SwellSync = {
    spotsUrl: cfg.spotsUrl,
    sessionsUrl: cfg.sessionsUrl,
    api: api,
    flash: flash,
    el: el,
    errorText: errorText
  };
}());
