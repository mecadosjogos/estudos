/* Player sincronizado com a transcrição (PLANO.md, fase 5).
 *
 * Tocar um parágrafo pula o áudio pro ponto certo; enquanto toca, o trecho
 * atual se destaca sozinho e a página rola acompanhando. Posição e
 * velocidade sobrevivem a fechar a aba — posição no servidor (pra retomar
 * de qualquer aparelho), velocidade só localStorage (preferência pessoal,
 * não por aula).
 */

function initReadingPage({ lessonId, hasAudio, initialPosition, editable }) {
	const params = new URLSearchParams(window.location.search);
	const seekParam = params.get("t");

	const segments = [...document.querySelectorAll(".segment")].map((el) => ({
		el,
		start: parseFloat(el.dataset.start),
		end: parseFloat(el.dataset.end),
	}));

	// loopEnd vai até o INÍCIO do próximo trecho, não o fim do próprio --
	// o Whisper deixa buracos entre trechos (pausa real, ou às vezes fala
	// que ele simplesmente não transcreveu), e parar exatamente no
	// end_s do trecho atual esconde esse buraco da revisão. Um caso real
	// já achado: uma frase inteira sumiu bem no meio de um buraco desses.
	segments.forEach((seg, i) => {
		const next = segments[i + 1];
		seg.loopEnd = next ? next.start : seg.end;
	});

	// Loop só entra ao abrir edição (duplo clique) -- clique simples e
	// "próximo de baixa confiança" tocam normal, sem prender o áudio no
	// trecho.
	let loopRange = null;

	function playSegment(seg) {
		seekTo(seg.start);
		audio.play();
	}

	function playSegmentLooped(seg) {
		loopRange = { start: seg.start, end: seg.loopEnd ?? seg.end };
		playSegment(seg);
	}

	// Botão "editar" (diferente do duplo clique, que já toca em loop): só
	// devolve o áudio pro início do trecho clicado e pausa ali, sem tocar
	// sozinho -- retoma só quando "Salvar" for clicado.
	function pauseAndSeek(seg) {
		loopRange = null;
		seekTo(seg.start);
		audio.pause();
	}

	segments.forEach((seg) => {
		seg.el.addEventListener("click", (ev) => {
			if (!hasAudio) return;
			if (ev.target.closest(".segment-edit-btn, textarea, .segment-edit-actions")) return;
			loopRange = null;
			playSegment(seg);
		});
	});

	if (editable) {
		initInlineEditing(
			lessonId,
			segments,
			hasAudio ? playSegmentLooped : null,
			hasAudio ? pauseAndSeek : null,
			hasAudio ? () => audio.play() : null
		);
	}

	const nextLowConfidenceBtn = document.getElementById("next-low-confidence");
	if (nextLowConfidenceBtn) {
		nextLowConfidenceBtn.addEventListener("click", () => {
			const flagged = segments.filter((s) => s.el.classList.contains("segment-low-confidence"));
			if (!flagged.length) return;
			const currentTime = hasAudio ? audio.currentTime : 0;
			const next = flagged.find((s) => s.start > currentTime + 0.5) || flagged[0];
			if (hasAudio) {
				loopRange = null;
				playSegment(next);
			}
			next.el.scrollIntoView({ behavior: "smooth", block: "center" });
		});
	}

	if (!hasAudio) return;

	const audio = document.getElementById("player-audio");
	const playPauseBtn = document.getElementById("player-playpause");
	const back15Btn = document.getElementById("player-back15");
	const fwd15Btn = document.getElementById("player-fwd15");
	const speedSelect = document.getElementById("player-speed");
	const speedDownBtn = document.getElementById("player-speed-down");
	const speedUpBtn = document.getElementById("player-speed-up");
	const autoscrollCheckbox = document.getElementById("player-autoscroll");
	const timeLabel = document.getElementById("player-time");

	const savedAutoscroll = localStorage.getItem("estudos-player-autoscroll");
	if (savedAutoscroll !== null) autoscrollCheckbox.checked = savedAutoscroll === "true";
	autoscrollCheckbox.addEventListener("change", () => {
		localStorage.setItem("estudos-player-autoscroll", String(autoscrollCheckbox.checked));
	});

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
		loopRange = null;
		audio.currentTime = Math.max(0, audio.currentTime - 15);
	});

	fwd15Btn.addEventListener("click", () => {
		loopRange = null;
		audio.currentTime = Math.min(audio.duration || Infinity, audio.currentTime + 15);
	});

	const speedSteps = [...speedSelect.options].map((opt) => parseFloat(opt.value));

	function setSpeed(value) {
		speedSelect.value = String(value);
		audio.playbackRate = value;
		localStorage.setItem("estudos-player-speed", String(value));
	}

	const savedSpeed = localStorage.getItem("estudos-player-speed");
	if (savedSpeed) setSpeed(parseFloat(savedSpeed));

	speedSelect.addEventListener("change", () => setSpeed(parseFloat(speedSelect.value)));

	function stepSpeed(direction) {
		const current = speedSteps.indexOf(parseFloat(speedSelect.value));
		const next = speedSteps[current + direction];
		if (next !== undefined) setSpeed(next);
	}
	speedDownBtn.addEventListener("click", () => stepSpeed(-1));
	speedUpBtn.addEventListener("click", () => stepSpeed(1));

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
		if (loopRange && audio.currentTime >= loopRange.end) {
			audio.currentTime = loopRange.start;
		}
	});

	let lastHighlighted = null;
	function highlightCurrentSegment() {
		const t = audio.currentTime;
		const current = segments.find((s) => t >= s.start && t < s.end);
		if (current === lastHighlighted) return;
		if (lastHighlighted) lastHighlighted.el.classList.remove("segment-active");
		if (current) {
			current.el.classList.add("segment-active");
			if (autoscrollCheckbox.checked) {
				current.el.scrollIntoView({ behavior: "smooth", block: "center" });
			}
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

/* Edição inline de um trecho (fase 8) — a correção precisa chegar no
 * banco antes de qualquer coisa usar essa transcrição (guia, aula
 * editada, cards), então salva no servidor a cada trecho, não só ao
 * final. Duplo clique no trecho abre a edição direto (sem precisar mirar
 * no botão "editar") e já toca o áudio em loop nele, pra corrigir
 * ouvindo repetidas vezes. */
function initInlineEditing(lessonId, segments, playSegmentLooped, pauseAndSeek, resume) {
	segments.forEach((seg) => {
		const segmentEl = seg.el;
		const btn = segmentEl.querySelector(".segment-edit-btn");
		if (!btn) return; // transcrição aprovada — sem edição

		function startEditing() {
			if (segmentEl.querySelector("textarea")) return; // já em edição

			const textSpan = segmentEl.querySelector(".segment-text");
			const segmentId = segmentEl.dataset.segmentId;
			const original = textSpan.textContent;

			const textarea = document.createElement("textarea");
			textarea.value = original;
			textarea.rows = 3;
			textarea.style.width = "100%";
			textarea.style.fontFamily = "inherit";

			const actions = document.createElement("div");
			actions.className = "segment-edit-actions button-row";
			const saveBtn = document.createElement("button");
			saveBtn.type = "button";
			saveBtn.textContent = "Salvar";
			const cancelBtn = document.createElement("button");
			cancelBtn.type = "button";
			cancelBtn.textContent = "Cancelar";
			actions.append(saveBtn, cancelBtn);

			textSpan.replaceWith(textarea);
			btn.after(actions);
			btn.hidden = true;
			textarea.focus();

			function restore(newText) {
				const span = document.createElement("span");
				span.className = "segment-text";
				span.textContent = newText;
				textarea.replaceWith(span);
				actions.remove();
				btn.hidden = false;
			}

			cancelBtn.addEventListener("click", (e) => {
				e.stopPropagation();
				restore(original);
			});

			saveBtn.addEventListener("click", async (e) => {
				e.stopPropagation();
				saveBtn.disabled = true;
				try {
					const response = await fetch(
						`/lessons/${lessonId}/transcricao/segments/${segmentId}`,
						{
							method: "POST",
							headers: { "Content-Type": "application/x-www-form-urlencoded" },
							credentials: "same-origin",
							body: `texto=${encodeURIComponent(textarea.value)}`,
						}
					);
					if (!response.ok) throw new Error(`falhou (${response.status})`);
					const data = await response.json();
					restore(data.text);
					if (!segmentEl.querySelector(".badge")) {
						const badge = document.createElement("span");
						badge.className = "badge";
						badge.textContent = "editado";
						btn.before(badge);
					}
					if (resume) resume();
				} catch (err) {
					alert(`Não foi possível salvar: ${err.message}`);
					saveBtn.disabled = false;
				}
			});
		}

		btn.addEventListener("click", (ev) => {
			ev.stopPropagation();
			if (pauseAndSeek) pauseAndSeek(seg);
			startEditing();
		});

		segmentEl.addEventListener("dblclick", (ev) => {
			if (ev.target.closest("textarea, .segment-edit-actions")) return;
			if (playSegmentLooped) playSegmentLooped(seg);
			startEditing();
		});
	});
}
