// Base URLs of the two services, read by the UI at load time.
// Locally these point at the host ports from docker-compose.yml.
// At deploy time the pipeline overwrites this file with the Azure URLs.
window.SWELLSYNC_CONFIG = {
  spotsUrl: "http://localhost:8001",
  sessionsUrl: "http://localhost:8002"
};
