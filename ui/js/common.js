/*
 * Shared browser helpers. Every call goes straight from the browser to a
 * service; the base URLs come from config.js. No framework, no build step.
 */
(function () {
  "use strict";

  var cfg = window.SWELLSYNC_CONFIG || {};

  // Waits between GET retries while a service wakes up, in milliseconds. After an
  // idle period Azure starts the container and resumes the paused database, which
  // takes about a minute; meanwhile it answers 503 "App port is not ready".
  var WAKE_DELAYS_MS = [2000, 4000, 8000, 8000, 8000, 8000, 8000, 8000, 8000, 8000, 8000];
  var STARTING_UP = "The service is starting up after being idle. This can take about a minute.";

  function once(base, path, init) {
    return fetch(base + path, init)
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

  function wait(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  // Resolves to { status, data }. A network failure resolves to status 0 with
  // a readable message, so pages can show a degraded state instead of hanging.
  // GETs retry through a cold start (status 0 or 503) and show a notice while
  // they wait. Writes are never retried, so a POST cannot be applied twice.
  function api(base, path, options) {
    options = options || {};
    var init = { method: options.method || "GET", headers: {} };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    if (init.method !== "GET") return once(base, path, init);

    var shownNotice = false;
    function attempt(n) {
      return once(base, path, init).then(function (result) {
        var waking = result.status === 0 || result.status === 503;
        if (!waking || n >= WAKE_DELAYS_MS.length) {
          if (shownNotice) clearNotice();
          return result;
        }
        if (!shownNotice) {
          flash(STARTING_UP + " Retrying…", "info");
          shownNotice = true;
        }
        return wait(WAKE_DELAYS_MS[n]).then(function () { return attempt(n + 1); });
      });
    }
    return attempt(0);
  }

  function clearNotice() {
    var box = document.getElementById("flash");
    if (!box) return;
    var info = box.querySelector(".flash-info");
    if (info) box.removeChild(info);
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
    if (data.error) return data.error;
    // Azure's own 503 during a cold start has no JSON body.
    if (result.status === 503) return STARTING_UP + " Try again in a minute.";
    return fallback;
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
