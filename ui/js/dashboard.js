// Dashboard: a composition view. It calls both services and shows whichever
// answers. If one is down, its numbers say so and the other still renders.
(function () {
  "use strict";
  var S = window.SwellSync;
  var el = S.el;

  function setText(id, text) { document.getElementById(id).textContent = text; }

  function loadSpots() {
    return S.api(S.spotsUrl, "/spots").then(function (r) {
      if (r.status !== 200) { setText("stat-spots", "—"); return []; }
      setText("stat-spots", String(r.data.spots.length));
      return r.data.spots;
    });
  }

  function loadStats() {
    return S.api(S.sessionsUrl, "/stats").then(function (r) {
      if (r.status !== 200) {
        setText("stat-sessions", "—"); setText("stat-hours", "—"); setText("stat-rating", "—");
        return;
      }
      var s = r.data.stats;
      setText("stat-sessions", String(s.session_count));
      setText("stat-hours", (s.total_duration_mins / 60).toFixed(1) + "h");
      setText("stat-rating", s.average_rating === null ? "—" : s.average_rating.toFixed(1));
    });
  }

  function loadRecent() {
    return S.api(S.sessionsUrl, "/sessions").then(function (r) {
      var tbody = document.getElementById("recent-rows");
      tbody.textContent = "";
      if (r.status !== 200) {
        tbody.appendChild(el("tr", {}, [el("td", { colspan: "4", className: "muted", text: S.errorText(r, "Sessions are unavailable.") })]));
        return;
      }
      if (r.data.notice) setText("recent-notice", r.data.notice);
      var recent = r.data.sessions.slice(0, 8);
      if (!recent.length) {
        tbody.appendChild(el("tr", {}, [el("td", { colspan: "4", className: "muted", text: "No sessions yet." })]));
        return;
      }
      recent.forEach(function (s) {
        tbody.appendChild(el("tr", {}, [
          el("td", { text: s.date }),
          el("td", { text: s.spot_name || ("spot #" + s.spot_id) }),
          el("td", { text: s.duration_mins + " min" }),
          el("td", { text: s.wave_or_wind_rating === null ? "—" : String(s.wave_or_wind_rating) })
        ]));
      });
    });
  }

  loadSpots();
  loadStats();
  loadRecent();
}());
