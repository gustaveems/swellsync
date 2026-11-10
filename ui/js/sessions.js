// Session log. Talks to the sessions service for sessions, and to the spots
// service only to fill the spot pickers. If spots are down, sessions still show
// (with a notice) and the picker says why it is empty.
(function () {
  "use strict";
  var S = window.SwellSync;
  var el = S.el;
  var editingId = null;

  function filterQuery() {
    var spot = document.getElementById("filter-spot").value;
    var sort = document.getElementById("filter-sort").value;
    var epic = document.getElementById("filter-epic").checked;
    var parts = [];
    if (spot) parts.push("spot=" + encodeURIComponent(spot));
    if (sort && sort !== "date") parts.push("sort=" + encodeURIComponent(sort));
    if (epic) parts.push("epic=1");
    return parts.join("&");
  }

  function loadSpotPickers(selectedSpot) {
    return S.api(S.spotsUrl, "/spots").then(function (r) {
      ["filter-spot", "form-spot"].forEach(function (id) {
        var select = document.getElementById(id);
        var keep = select.options[0];
        select.textContent = "";
        select.appendChild(keep);
        if (r.status !== 200) {
          select.appendChild(el("option", { value: "", text: "Spots unavailable" }));
          select.disabled = id === "form-spot";
          return;
        }
        select.disabled = false;
        r.data.spots.forEach(function (s) {
          var opt = el("option", { value: String(s.id), text: s.name });
          if (String(s.id) === String(selectedSpot)) opt.selected = true;
          select.appendChild(opt);
        });
      });
      return r.status === 200;
    });
  }

  function renderSessions() {
    var q = filterQuery();
    document.getElementById("export-link").href = S.sessionsUrl + "/sessions/export.csv" + (q ? "?" + q : "");
    return S.api(S.sessionsUrl, "/sessions" + (q ? "?" + q : "")).then(function (r) {
      var tbody = document.getElementById("session-rows");
      var notice = document.getElementById("list-notice");
      tbody.textContent = "";
      notice.textContent = r.status === 200 && r.data.notice ? r.data.notice : "";
      if (r.status !== 200) {
        tbody.appendChild(el("tr", {}, [el("td", { colspan: "7", className: "muted", text: S.errorText(r, "Sessions are unavailable.") })]));
        return;
      }
      if (!r.data.sessions.length) {
        tbody.appendChild(el("tr", {}, [el("td", { colspan: "7", className: "muted", text: "No sessions match." })]));
        return;
      }
      r.data.sessions.forEach(function (s) {
        var edit = el("button", { type: "button", className: "btn btn-secondary btn-tiny", text: "Edit" });
        var del = el("button", { type: "button", className: "btn btn-danger btn-tiny", text: "Delete" });
        edit.addEventListener("click", function () { startEdit(s); });
        del.addEventListener("click", function () {
          if (!window.confirm("Delete this session?")) return;
          S.api(S.sessionsUrl, "/sessions/" + s.id, { method: "DELETE" }).then(function (d) {
            if (d.status === 204) { S.flash("Session deleted.", "success"); renderSessions(); }
            else S.flash(S.errorText(d, "Could not delete the session."), "error");
          });
        });
        tbody.appendChild(el("tr", {}, [
          el("td", { text: s.date }),
          el("td", { text: s.spot_name || ("spot #" + s.spot_id) }),
          el("td", { text: s.duration_mins + " min" }),
          el("td", { text: String(s.wave_or_wind_rating) }),
          el("td", { text: s.gear_used || "—" }),
          el("td", { className: "notes-cell", text: s.notes || "" }),
          el("td", { className: "actions-cell" }, [edit, document.createTextNode(" "), del])
        ]));
      });
    });
  }

  function formBody(form) {
    var raw = Object.fromEntries(new FormData(form).entries());
    return {
      spot_id: raw.spot_id ? Number(raw.spot_id) : null,
      date: raw.date || "",
      duration_mins: raw.duration_mins ? Number(raw.duration_mins) : raw.duration_mins,
      wave_or_wind_rating: raw.wave_or_wind_rating ? Number(raw.wave_or_wind_rating) : raw.wave_or_wind_rating,
      gear_used: raw.gear_used || null,
      notes: raw.notes || null
    };
  }

  function startEdit(s) {
    editingId = s.id;
    var form = document.getElementById("session-form");
    form.elements.spot_id.value = String(s.spot_id);
    form.elements.date.value = s.date;
    form.elements.duration_mins.value = s.duration_mins;
    form.elements.wave_or_wind_rating.value = String(s.wave_or_wind_rating);
    form.elements.gear_used.value = s.gear_used || "";
    form.elements.notes.value = s.notes || "";
    document.getElementById("form-title").textContent = "Edit session";
    document.getElementById("submit-session").textContent = "Save changes";
    document.getElementById("cancel-edit").hidden = false;
    window.location.hash = "log-session";
  }

  function stopEdit() {
    editingId = null;
    document.getElementById("session-form").reset();
    document.getElementById("form-title").textContent = "Log a session";
    document.getElementById("submit-session").textContent = "Log session";
    document.getElementById("cancel-edit").hidden = true;
  }

  function bindForm() {
    document.getElementById("cancel-edit").addEventListener("click", stopEdit);
    document.getElementById("session-form").addEventListener("submit", function (event) {
      event.preventDefault();
      var body = formBody(this);
      var request = editingId
        ? S.api(S.sessionsUrl, "/sessions/" + editingId, { method: "PUT", body: body })
        : S.api(S.sessionsUrl, "/sessions", { method: "POST", body: body });
      request.then(function (r) {
        if (r.status === 200 || r.status === 201) {
          S.flash(editingId ? "Session updated." : "Session logged. 🤙", "success");
          stopEdit();
          renderSessions();
        } else {
          S.flash(S.errorText(r, "Could not save the session."), "error");
        }
      });
    });
    document.getElementById("filter-form").addEventListener("submit", function (event) {
      event.preventDefault();
      renderSessions();
    });
    document.getElementById("filter-epic").addEventListener("change", renderSessions);
    document.getElementById("filter-sort").addEventListener("change", renderSessions);
    document.getElementById("filter-spot").addEventListener("change", renderSessions);
  }

  bindForm();
  loadSpotPickers().then(renderSessions);
}());
