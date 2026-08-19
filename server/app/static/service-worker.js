// PLANO.md fase 7: cache offline da fila do dia — sem isso, sem sinal no
// meio do trajeto significa sem revisão nenhuma naquele dia.
const CACHE_NAME = "estudos-review-v1";
const APP_SHELL = ["/static/style.css", "/static/reading.js", "/static/manifest.json"];

self.addEventListener("install", (event) => {
	event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
	self.skipWaiting();
});

self.addEventListener("activate", (event) => {
	event.waitUntil(
		caches.keys().then((keys) =>
			Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
		)
	);
	self.clients.claim();
});

self.addEventListener("fetch", (event) => {
	const { request } = event;
	if (request.method !== "GET") return;

	const url = new URL(request.url);
	// O registro (review.html) restringe o escopo a /revisao -- então este
	// worker só controla a fila de revisão, nunca outra página do site
	// (ex.: /upload). "/" fica de fora por causa disso.
	const isReviewPage = url.pathname === "/revisao";
	const isAudio = url.pathname.startsWith("/lessons/") && url.pathname.endsWith("/audio");

	if (isAudio) return; // áudio original não entra no cache — pesado e a rede já é o critério de "ouvir o original"

	if (isReviewPage) {
		// network-first: fila sempre atualizada quando há sinal; cache é só o
		// fallback pra quando o sinal cai no meio do trajeto.
		event.respondWith(
			fetch(request)
				.then((response) => {
					const copy = response.clone();
					caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
					return response;
				})
				.catch(() => caches.match(request))
		);
		return;
	}

	event.respondWith(
		caches.match(request).then((cached) => cached || fetch(request))
	);
});
