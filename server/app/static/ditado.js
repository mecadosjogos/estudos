// Ditado por voz numa <textarea> (PLANO.md, fase 13b -- dissertativas).
//
// Um botão liga e desliga. Enquanto liga, o que você fala aparece em cinza
// (resultado provisório) e, quando o reconhecimento fecha a frase, entra no
// texto NO PONTO DO CURSOR -- dá pra clicar no meio do texto e ditar ali,
// ou parar, corrigir à mão e voltar a ditar.
//
// Usa o reconhecimento do próprio Chrome/Edge (webkitSpeechRecognition): é o
// único jeito de transcrever AO VIVO enquanto se fala. O áudio vai pro
// serviço de voz do navegador (Google, no Chrome) -- o mesmo que os comandos
// de voz do "Dominar o guia" já usam.
//
// Pontuação falada: "vírgula", "ponto final", "ponto de interrogação",
// "dois pontos", "ponto e vírgula", "abre parênteses", "fecha parênteses",
// "nova linha", "novo parágrafo".
(() => {
	const PONTUACAO = [
		[/\s*\bnovo par[áa]grafo\b\s*/gi, "\n\n"],
		[/\s*\bnova linha\b\s*/gi, "\n"],
		[/\s*\bponto de interroga[çc][ãa]o\b/gi, "?"],
		[/\s*\bponto de exclama[çc][ãa]o\b/gi, "!"],
		[/\s*\bponto e v[íi]rgula\b/gi, ";"],
		[/\s*\bponto final\b/gi, "."],
		[/\s*\bdois pontos\b/gi, ":"],
		[/\s*\bv[íi]rgula\b/gi, ","],
		[/\s*\babre par[êe]nteses\b\s*/gi, " ("],
		[/\s*\bfecha par[êe]nteses\b/gi, ")"],
	];

	function aplicarPontuacao(frase) {
		let texto = frase;
		for (const [regex, sinal] of PONTUACAO) texto = texto.replace(regex, sinal);
		return texto.replace(/ +([,.;:?!)])/g, "$1");
	}

	function capitalizar(texto) {
		return texto.charAt(0).toUpperCase() + texto.slice(1);
	}

	window.criarDitado = function criarDitado({ textarea, botao, indicador, previa, aoMudar }) {
		const Reconhecimento = window.SpeechRecognition || window.webkitSpeechRecognition;
		if (!Reconhecimento) {
			botao.disabled = true;
			botao.title = "Ditado não suportado neste navegador — use Chrome ou Edge.";
			if (indicador) indicador.textContent = "ditado só no Chrome/Edge";
			return { ativo: () => false, parar: () => {} };
		}

		let rec = null;
		let pararManual = true;
		let cursor = null;

		function estado(nome, texto) {
			if (!indicador) return;
			indicador.hidden = nome === "off";
			indicador.dataset.estado = nome;
			indicador.textContent = texto || "";
		}

		function mostrarPrevia(texto) {
			if (!previa) return;
			previa.hidden = !texto;
			previa.textContent = texto ? "ouvindo: " + texto : "";
		}

		function inserir(fraseCrua) {
			let frase = aplicarPontuacao(fraseCrua.trim());
			if (!frase) return;
			const valor = textarea.value;
			// Cursor: onde a pessoa clicou por último; se o foco saiu da
			// caixa, continua de onde o ditado parou.
			let pos = document.activeElement === textarea ? textarea.selectionStart : cursor;
			if (pos === null || pos > valor.length) pos = valor.length;
			const antes = valor.slice(0, pos);
			const depois = valor.slice(pos);

			const ultimo = antes.replace(/[ \t]+$/, "").slice(-1);
			if (ultimo === "" || /[.?!\n]/.test(ultimo)) frase = capitalizar(frase.replace(/^\s+/, ""));
			const precisaEspaco = antes.length > 0 && !/[\s(]$/.test(antes) && !/^[\s,.;:?!)]/.test(frase);
			const pedaco = (precisaEspaco ? " " : "") + frase;

			textarea.value = antes + pedaco + depois;
			cursor = pos + pedaco.length;
			textarea.setSelectionRange(cursor, cursor);
			if (aoMudar) aoMudar();
		}

		function iniciar() {
			rec = new Reconhecimento();
			rec.lang = "pt-BR";
			rec.continuous = true;
			rec.interimResults = true;

			rec.onspeechstart = () => estado("captando", "ouvindo…");
			rec.onspeechend = () => estado("interpretando", "transcrevendo…");
			rec.onresult = (ev) => {
				let provisorio = "";
				for (let i = ev.resultIndex; i < ev.results.length; i++) {
					const r = ev.results[i];
					if (r.isFinal) {
						inserir(r[0].transcript);
					} else {
						provisorio += r[0].transcript;
					}
				}
				mostrarPrevia(provisorio.trim());
				estado("captando", provisorio ? "ouvindo…" : "ditando — fale");
			};
			rec.onerror = (ev) => {
				if (ev.error === "not-allowed" || ev.error === "service-not-allowed") {
					pararManual = true;
					estado("falhou", "permissão de microfone negada");
					botao.textContent = "🎙 Ditar";
				} else if (ev.error !== "no-speech" && ev.error !== "aborted") {
					estado("falhou", "falha no microfone — tentando de novo");
				}
			};
			rec.onend = () => {
				mostrarPrevia("");
				// O Chrome encerra sozinho depois de um silêncio; enquanto o
				// ditado está ligado, reinicia. Adiado e protegido: chamado
				// direto dentro do onend às vezes estoura InvalidStateError
				// (mesmo achado do guia_praticar.html).
				if (pararManual) {
					estado("off");
					return;
				}
				setTimeout(() => {
					if (pararManual || !rec) return;
					try {
						rec.start();
					} catch (erro) {
						estado("falhou", "o microfone parou — clique em Parar e Ditar de novo");
					}
				}, 150);
			};
			rec.start();
			botao.textContent = "⏹ Parar ditado";
			botao.classList.add("ditando");
			estado("aguardando", "ditando — fale");
		}

		function parar() {
			pararManual = true;
			if (rec) rec.stop();
			rec = null;
			botao.textContent = "🎙 Ditar";
			botao.classList.remove("ditando");
			mostrarPrevia("");
			estado("off");
		}

		textarea.addEventListener("click", () => { cursor = textarea.selectionStart; });
		textarea.addEventListener("keyup", () => { cursor = textarea.selectionStart; });

		botao.addEventListener("click", () => {
			if (rec) {
				parar();
			} else {
				pararManual = false;
				cursor = textarea.selectionStart ?? textarea.value.length;
				iniciar();
			}
		});

		return { ativo: () => rec !== null, parar };
	};
})();
