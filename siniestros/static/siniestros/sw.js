// Guarda el formulario de captura en el teléfono para que abra aunque no haya señal.
// Solo se guardan la pantalla de captura y los archivos estáticos; los reportes
// de la plataforma siempre se piden al servidor (no se dejan copias en el teléfono).
const CACHE = "siniestros-v4";
const BASICOS = ["/manifest.json", "/static/siniestros/icon-192.png", "/static/siniestros/icon-512.png",
                 "/static/siniestros/logo-blanco.png", "/static/siniestros/firma_perito_htt.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(BASICOS)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  const esCaptura = url.pathname === "/";
  const esEstatico = url.pathname.startsWith("/static/") || url.pathname === "/manifest.json";
  if (!esCaptura && !esEstatico) return;
  // Primero la red (versión más nueva); si no hay señal, lo guardado
  e.respondWith(
    fetch(e.request).then(r => {
      // no se guarda si nos mandó al login (sesión cerrada)
      if (r.ok && !r.redirected) { const copia = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copia)); }
      return r;
    }).catch(() => caches.match(e.request))
  );
});
