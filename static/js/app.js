/*
 * SwellSync — behaviour layer (static/js/app.js)
 *
 * Loaded with `defer` from the same origin, which is all the Content-Security-
 * Policy in app.py allows for script-src. Nothing here is required to submit a
 * form: with JavaScript unavailable, the confirm prompt is simply skipped and
 * the filter forms fall back to their <noscript> Apply button.
 */
(function () {
  "use strict";

  // Destructive actions ask first. <form data-confirm="message">
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form.hasAttribute && form.hasAttribute("data-confirm")) {
      if (!window.confirm(form.getAttribute("data-confirm"))) {
        event.preventDefault();
      }
    }
  });

  // Filter controls submit their own form when they change.
  // <select|input data-autosubmit>
  document.addEventListener("change", function (event) {
    var control = event.target;
    if (control.hasAttribute && control.hasAttribute("data-autosubmit") && control.form) {
      control.form.submit();
    }
  });
}());
