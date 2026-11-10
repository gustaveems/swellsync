// Spot directory page. Talks only to the spots service, except the detail view,
// which also asks the sessions service for that spot's numbers.
(function () {
  "use strict";
  var S = window.SwellSync;
  var el = S.el;
  var params = new URLSearchParams(window.location.search);
  var spotId = params.get("id");

  function formToBody(form) {
    var raw = Object.fromEntries(new FormData(form).entries());
    return {
      name: raw.name || "",
      location: raw.location || "",
      ideal_wind_dir: raw.ideal_wind_dir || null,
      ideal_swell_ft: raw.ideal_swell_ft && raw.ideal_swell_ft.trim() ? raw.ideal_swell_ft : null
    };
  }

  // ---- list view ----------------------------------------------------------

  function renderList(q) {
    var path = "/spots" + (q ? "?q=" + encodeURIComponent(q) : "");
    return S.api(S.spotsUrl, path).then(function (r) {
      var tbody = document.getElementById("spot-rows");
      tbody.textContent = "";
      if (r.status !== 200) {
        tbody.appendChild(el("tr", {}, [el("td", { colspan: "4", className: "muted", text: S.errorText(r, "Spots are unavailable.") })]));
        return;
      }
      if (!r.data.spots.length) {
        tbody.appendChild(el("tr", {}, [el("td", { colspan: "4", className: "muted", text: "No spots match." })]));
        return;
      }
      r.data.spots.forEach(function (s) {
        var link = el("a", { href: "spots.html?id=" + s.id, text: s.name, className: "spot-link" });
        tbody.appendChild(el("tr", {}, [
          el("td", {}, [link]),
          el("td", { text: s.location }),
          el("td", { text: s.ideal_wind_dir || "—" }),
          el("td", { text: s.ideal_swell_ft === null ? "—" : s.ideal_swell_ft + " ft" })
        ]));
      });
    });
  }

  function bindList() {
    var q = new URLSearchParams(window.location.search).get("q") || "";
    document.getElementById("q").value = q;
    renderList(q);
    document.getElementById("search-form").addEventListener("submit", function (event) {
      event.preventDefault();
      var term = document.getElementById("q").value.trim();
      renderList(term);
    });
    document.getElementById("spot-form").addEventListener("submit", function (event) {
      event.preventDefault();
      S.api(S.spotsUrl, "/spots", { method: "POST", body: formToBody(this) }).then(function (r) {
        if (r.status === 201) {
          S.flash("Spot “" + r.data.name + "” added to the directory.", "success");
          window.location.reload();
        } else {
          S.flash(S.errorText(r, "Could not add the spot."), "error");
        }
      });
    });
  }

  // ---- detail view --------------------------------------------------------

  function fillEditForm(spot) {
    var form = document.getElementById("edit-spot-form");
    form.elements.name.value = spot.name;
    form.elements.location.value = spot.location;
    form.elements.ideal_wind_dir.value = spot.ideal_wind_dir || "";
    form.elements.ideal_swell_ft.value = spot.ideal_swell_ft === null ? "" : spot.ideal_swell_ft;
  }

  function loadSessionNumbers(id) {
    S.api(S.sessionsUrl, "/stats?spot=" + id).then(function (r) {
      if (r.status !== 200) {
        document.getElementById("detail-notice").textContent =
          "Session figures are unavailable right now: " + S.errorText(r, "the sessions service did not answer.");
        return;
      }
      var s = r.data.stats;
      document.getElementById("d-count").textContent = String(s.session_count);
      document.getElementById("d-hours").textContent = (s.total_duration_mins / 60).toFixed(1) + "h";
      document.getElementById("d-rating").textContent = s.average_rating === null ? "—" : s.average_rating.toFixed(1);
    });
    S.api(S.sessionsUrl, "/sessions?spot=" + id + "&epic=1").then(function (r) {
      var tbody = document.getElementById("epic-rows");
      tbody.textContent = "";
      if (r.status !== 200) {
        tbody.appendChild(el("tr", {}, [el("td", { colspan: "4", className: "muted", text: "Unavailable while the sessions service is down." })]));
        return;
      }
      if (!r.data.sessions.length) {
        tbody.appendChild(el("tr", {}, [el("td", { colspan: "4", className: "muted", text: "No rated-4+ sessions here yet." })]));
        return;
      }
      r.data.sessions.forEach(function (s) {
        tbody.appendChild(el("tr", {}, [
          el("td", { text: s.date }),
          el("td", { text: s.duration_mins + " min" }),
          el("td", { text: String(s.wave_or_wind_rating) }),
          el("td", { text: s.gear_used || "—" })
        ]));
      });
    });
  }

  function bindDetail(id) {
    document.getElementById("list-view").hidden = true;
    document.getElementById("detail-view").hidden = false;

    S.api(S.spotsUrl, "/spots/" + id).then(function (r) {
      if (r.status !== 200) {
        document.getElementById("detail-name").textContent = "Spot not available";
        S.flash(S.errorText(r, "This spot could not be loaded."), "error");
        return;
      }
      var spot = r.data;
      document.getElementById("detail-name").textContent = spot.name;
      document.getElementById("detail-location").textContent = spot.location;
      fillEditForm(spot);
    });
    loadSessionNumbers(id);

    document.getElementById("edit-spot-form").addEventListener("submit", function (event) {
      event.preventDefault();
      S.api(S.spotsUrl, "/spots/" + id, { method: "PUT", body: formToBody(this) }).then(function (r) {
        if (r.status === 200) {
          S.flash("Spot updated.", "success");
          document.getElementById("detail-name").textContent = r.data.name;
          document.getElementById("detail-location").textContent = r.data.location;
        } else {
          S.flash(S.errorText(r, "Could not save the spot."), "error");
        }
      });
    });

    document.getElementById("delete-spot").addEventListener("click", function () {
      if (!window.confirm("Delete this spot? This cannot be undone.")) return;
      S.api(S.spotsUrl, "/spots/" + id, { method: "DELETE" }).then(function (r) {
        if (r.status === 204) {
          window.location.href = "spots.html";
        } else {
          // 409 when sessions still reference the spot; 503 when that cannot be checked.
          S.flash(S.errorText(r, "Could not delete the spot."), "error");
        }
      });
    });
  }

  if (spotId) bindDetail(spotId);
  else bindList();
}());
