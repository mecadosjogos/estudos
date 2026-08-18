/* Player sincronizado com a transcrição (PLANO.md, fase 5).
 *
 * Tocar um parágrafo pula o áudio pro ponto certo; enquanto toca, o trecho
 * atual se destaca sozinho e a página rola acompanhando. Posição e
 * velocidade sobrevivem a fechar a aba — posição no servidor (pra retomar
 * de qualquer aparelho), velocidade só localStorage (preferência pessoal,
 * não por aula).
 */

function initReadingPage({ lessonId, hasAudio, initialPosition }) {
	const params = new URLSearchParams(window.location.search);
	const seekParam = params.get("t");

	const segments = [...document.querySelectorAll(".segment")].map((el) => ({
		el,
		start: parseFloat(el.dataset.start),
		end: parseFloat(el.dataset.end),
	}));

	segments.forEach((seg) => {
		seg.el.addEventListener("click", () => {
			if (!hasAudio) return;
			seekTo(seg.start);
			audio.play();
		});
	});

	if (!hasAudio) return;

	const audio = document.getElementById("player-audio");
	const playPauseBtn = document.getElementById("player-playpause");
	const back15Btn = document.getElementById("player-back15");
	const fwd15Btn = document.getElementById("player-fwd15");
	const speedSelect = document.getElementById("player-speed");
	const timeLabel = document.getElementById("player-time");

	function formatTime(s) {
		if (!isFinite(s)) return "00:00";
		const m = Math.floor(s / 60);
		const sec = Math.floor(s % 60);
		return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
	}

	function seekTo(seconds) {
		audio.currentTime = seconds;
	}

	playPauseBtn.addEventListener("click", () => {
		if (audio.paused) audio.play();
		else audio.pause();
	});

	back15Btn.addEventListener("click", () => {
		audio.currentTime = Math.max(0, audio.currentTime - 15);
	});

	fwd15Btn.addEventListener("click", () => {
		audio.currentTime = Math.min(audio.duration || Infinity, audio.currentTime + 15);
	});

	const savedSpeed = localStorage.getItem("estudos-player-speed");
	if (savedSpeed) {
		speedSelect.value = savedSpeed;
		audio.playbackRate = parseFloat(savedSpeed);
	}
	speedSelect.addEventListener("change", () => {
		audio.playbackRate = parseFloat(speedSelect.value);
		localStorage.setItem("estudos-player-speed", speedSelect.value);
	});

	audio.addEventListener("play", () => {
		playPauseBtn.textContent = "⏸ Pausar";
	});
	audio.addEventListener("pause", () => {
		playPauseBtn.textContent = "▸ Tocar";
		savePosition();
	});

	audio.addEventListener("timeupdate", () => {
		timeLabel.textContent = `${formatTime(audio.currentTime)} / ${formatTime(audio.duration)}`;
		highlightCurrentSegment();
	});

	let lastHighlighted = null;
	function highlightCurrentSegment() {
		const t = audio.currentTime;
		const current = segments.find((s) => t >= s.start && t < s.end);
		if (current === lastHighlighted) return;
		if (lastHighlighted) lastHighlighted.el.classList.remove("segment-active");
		if (current) {
			current.el.classList.add("segment-active");
			current.el.scrollIntoView({ behavior: "smooth", block: "center" });
		}
		lastHighlighted = current || null;
	}

	let lastSavedAt = 0;
	function savePosition() {
		const now = Date.now();
		if (now - lastSavedAt < 4000) return;
		lastSavedAt = now;
		fetch(`/lessons/${lessonId}/posicao`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			credentials: "same-origin",
			body: JSON.stringify({ posicao_s: audio.currentTime }),
		}).catch(() => {
			// falha ao salvar posição não deve incomodar quem está estudando
		});
	}

	audio.addEventListener("timeupdate", () => {
		if (!audio.paused) savePosition();
	});

	window.addEventListener("beforeunload", () => {
		if (!isNaN(audio.currentTime)) {
			navigator.sendBeacon(
				`/lessons/${lessonId}/posicao`,
				new Blob([JSON.stringify({ posicao_s: audio.currentTime })], { type: "application/json" })
			);
		}
	});

	audio.addEventListener("loadedmetadata", () => {
		if (seekParam) {
			seekTo(parseFloat(seekParam));
		} else if (initialPosition > 0) {
			seekTo(initialPosition);
		}
		timeLabel.textContent = `${formatTime(audio.currentTime)} / ${formatTime(audio.duration)}`;
	});

	if ("mediaSession" in navigator) {
		navigator.mediaSession.metadata = new MediaMetadata({
			title: document.title,
			artist: "Estudos",
		});
		navigator.mediaSession.setActionHandler("play", () => audio.play());
		navigator.mediaSession.setActionHandler("pause", () => audio.pause());
		navigator.mediaSession.setActionHandler("seekbackward", () => {
			audio.currentTime = Math.max(0, audio.currentTime - 15);
		});
		navigator.mediaSession.setActionHandler("seekforward", () => {
			audio.currentTime = Math.min(audio.duration || Infinity, audio.currentTime + 15);
		});
		navigator.mediaSession.setActionHandler("seekto", (details) => {
			if (details.seekTime != null) seekTo(details.seekTime);
		});
	}
}
