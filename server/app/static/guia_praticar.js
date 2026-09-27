// "Dominar o guia" -- tela de prática (templates/guia_praticar.html).
//
// Três peças que conversam por eventos no `document`:
//   - troca no lugar: responder/ajustar/remover enviam por fetch e trocam só
//     #praticar-conteudo, sem recarregar a página. Recarregar travava o
//     autoplay da locução no celular (o navegador só deixa tocar som numa
//     página que já recebeu um toque, e página nova começa do zero) e
//     reiniciava o microfone a cada questão.
//   - locutor: lê a pergunta ao aparecer e a resposta ao revelar -- o mp3
//     narrado pelo TTS local quando existe, a voz do navegador enquanto não.
//     Avisa "locucao:inicio" e "locucao:fim".
//   - comando de voz: pausa o microfone entre esses dois eventos, pra não
//     captar a própria locução.
(() => {
	const lessonId = document.getElementById("praticar-conteudo").dataset.lessonId;

	function lerPreferencia(chave) {
		try {
			return localStorage.getItem(chave) === "1";
		} catch (erro) {
			return false;
		}
	}

	function gravarPreferencia(chave, ligada) {
		try {
			if (ligada) localStorage.setItem(chave, "1");
			else localStorage.removeItem(chave);
		} catch (erro) {
			// sem armazenamento (aba anônima, dados bloqueados): só não lembra
		}
	}

	const card = () => document.getElementById("exercicio-card");
	function gabaritoVisivel() {
		const passo = document.getElementById("gabarito-step");
		return !!passo && !passo.hidden;
	}

	// --- locutor ------------------------------------------------------------

	const locutor = (() => {
		const CHAVE = "guia-praticar-locucao-ativa";
		const player = document.getElementById("locucao-player");
		const toggleBtn = document.getElementById("locucao-toggle-btn");
		const tocarWrap = document.getElementById("locucao-tocar-wrap");
		const tocarBtn = document.getElementById("locucao-tocar-btn");
		const statusEl = document.getElementById("locucao-status");
		const sintese = window.speechSynthesis || null;

		let ativa = false;
		let falando = false;
		let pedidoFeito = false;
		// Cada fala nova invalida os callbacks da anterior: parar uma fala
		// dispara o erro/fim dela depois, já com a próxima tocando, e isso
		// não pode soltar o microfone no meio da fala nova.
		let geracao = 0;
		let parteBarrada = null;

		function comecou() {
			if (falando) return;
			falando = true;
			document.dispatchEvent(new CustomEvent("locucao:inicio"));
		}

		function terminou() {
			if (!falando) return;
			falando = false;
			document.dispatchEvent(new CustomEvent("locucao:fim"));
		}

		function parar() {
			geracao++;
			player.pause();
			if (sintese) sintese.cancel();
			terminou();
		}

		// O navegador barrou o som (nenhum toque na página ainda): um botão
		// grande pro polegar. Depois desse toque, o resto segue sozinho.
		function pedirToque(parte) {
			parteBarrada = parte;
			tocarWrap.hidden = false;
		}

		tocarBtn.addEventListener("click", () => {
			tocarWrap.hidden = true;
			falar(parteBarrada || "pergunta");
		});

		function vozPortugues() {
			const vozes = sintese.getVoices();
			return (
				vozes.find((v) => v.lang === "pt-BR") ||
				vozes.find((v) => v.lang.replace("_", "-").toLowerCase().startsWith("pt")) ||
				null
			);
		}

		// Frases curtas, uma fila de falas: o Chrome corta sozinho uma fala
		// longa depois de uns 15 s (recordação livre passa disso fácil).
		function pedacos(texto) {
			const frases = texto.split(/(?<=[.!?;:])\s+/);
			const saida = [];
			let atual = "";
			for (const frase of frases) {
				if (atual && (atual + " " + frase).length > 180) {
					saida.push(atual);
					atual = frase;
				} else {
					atual = atual ? atual + " " + frase : frase;
				}
			}
			if (atual) saida.push(atual);
			return saida;
		}

		// Fala em andamento guardada aqui: sem referência, o Chrome coleta o
		// objeto no meio da fala e o `onend` dele nunca chega.
		let falaAtual = null;

		// Um trecho de cada vez, o próximo só no fim do anterior. Enfileirar
		// todos de uma vez no speechSynthesis travava a fila no Chrome depois
		// do primeiro -- respostas de vários pontos paravam no primeiro.
		function sintetizar(texto, parte, minha) {
			if (!sintese || !texto) return;
			const trechos = pedacos(texto);
			const voz = vozPortugues();
			comecou();
			const falarTrecho = (i) => {
				if (minha !== geracao) return;
				if (i >= trechos.length) {
					falaAtual = null;
					terminou();
					return;
				}
				const fala = new SpeechSynthesisUtterance(trechos[i]);
				fala.lang = "pt-BR";
				if (voz) fala.voice = voz;
				fala.onend = () => falarTrecho(i + 1);
				fala.onerror = (ev) => {
					if (minha !== geracao) return;
					falaAtual = null;
					sintese.cancel();
					terminou();
					if (ev.error === "not-allowed") pedirToque(parte);
				};
				falaAtual = fala;
				sintese.speak(fala);
			};
			falarTrecho(0);
		}

		function falar(parte) {
			const alvo = card();
			if (!alvo) return;
			parar();
			const minha = geracao;
			tocarWrap.hidden = true;
			const url = alvo.dataset[parte + "Url"];
			const texto = alvo.dataset[parte + "Texto"];
			if (!url) {
				sintetizar(texto, parte, minha);
				return;
			}
			const daVez = (fn) => () => {
				if (minha === geracao) fn();
			};
			player.onended = daVez(terminou);
			player.onerror = daVez(terminou);
			// Pausa vinda de fora (controle de mídia da tela bloqueada): sem
			// isso o microfone ficaria parado esperando um fim que não vem.
			// Só vale depois que ESTE áudio começa: o `pause` do áudio anterior,
			// parado pelo `parar()` acima, chega atrasado e soltava o microfone
			// no meio da resposta.
			player.onpause = null;
			player.onplaying = daVez(() => {
				player.onpause = daVez(() => {
					if (!player.ended) terminou();
				});
			});
			player.src = url;
			// Avisa antes do som sair: o microfone precisa parar antes, não
			// depois do primeiro pedaço da fala já ter entrado nele.
			comecou();
			player.play().catch((erro) => {
				if (minha !== geracao) return;
				terminou();
				if (erro.name === "NotAllowedError") {
					pedirToque(parte);
					return;
				}
				// mp3 sumiu/falhou: lê pelo navegador, numa geração nova pra o
				// erro atrasado do player não encerrar essa fala.
				geracao++;
				sintetizar(texto, parte, geracao);
			});
		}

		// Pede à VPS os áudios que faltam nesta aula (o worker com o
		// tts-service de pé vai narrando e subindo um a um). Uma vez por
		// carregamento de página basta: as próximas questões já chegam com o
		// que ficou pronto no meio-tempo.
		function pedirGeracao() {
			if (pedidoFeito) return;
			pedidoFeito = true;
			fetch("/lessons/" + lessonId + "/guia/locucao", { method: "POST", credentials: "same-origin" })
				.then((resp) => (resp.ok ? resp.json() : null))
				.then((dados) => {
					if (!dados || !dados.pendentes) return;
					statusEl.hidden = false;
					statusEl.textContent =
						"🔊 " + dados.pendentes + " áudio(s) desta aula na fila de narração — enquanto isso, lê a voz do navegador.";
				})
				.catch(() => {});
		}

		function ligar(lerAgora) {
			ativa = true;
			gravarPreferencia(CHAVE, true);
			toggleBtn.textContent = "🔇 Desativar locução";
			pedirGeracao();
			if (lerAgora && card()) falar(gabaritoVisivel() ? "resposta" : "pergunta");
		}

		function desligar() {
			ativa = false;
			gravarPreferencia(CHAVE, false);
			toggleBtn.textContent = "🔊 Ativar locução";
			tocarWrap.hidden = true;
			statusEl.hidden = true;
			parar();
		}

		toggleBtn.addEventListener("click", () => (ativa ? desligar() : ligar(true)));

		if (!sintese && !player.canPlayType("audio/mpeg")) {
			toggleBtn.disabled = true;
			toggleBtn.title = "Este navegador não toca áudio nem tem voz sintética.";
		}

		return {
			falar,
			parar,
			// Tocar logo ao abrir a página: sem um toque antes, o navegador
			// pode barrar -- aí aparece o "Toque para ouvir".
			iniciar() {
				if (lerPreferencia(CHAVE)) ligar(false);
			},
			aoCarregarCard() {
				tocarWrap.hidden = true;
				if (ativa && card()) falar("pergunta");
			},
			aoRevelar() {
				if (ativa) falar("resposta");
			},
		};
	})();

	// --- card: handlers e troca no lugar ----------------------------------

	let enviando = false;

	async function enviarTrocando(form) {
		if (enviando) return;
		enviando = true;
		locutor.parar();
		let resp;
		try {
			resp = await fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin" });
		} catch (erro) {
			// Nem chegou ao servidor: envio normal, com recarga.
			enviando = false;
			HTMLFormElement.prototype.submit.call(form);
			return;
		}
		try {
			if (!resp.ok) throw new Error("HTTP " + resp.status);
			const doc = new DOMParser().parseFromString(await resp.text(), "text/html");
			const novo = doc.getElementById("praticar-conteudo");
			if (!novo) throw new Error("resposta sem #praticar-conteudo");
			document.getElementById("praticar-conteudo").innerHTML = novo.innerHTML;
			montarConteudo();
			document.dispatchEvent(new CustomEvent("praticar:novo-card"));
		} catch (erro) {
			// O POST já foi (não reenviar -- contaria a resposta duas vezes):
			// só carrega a página de onde o servidor mandou ir.
			window.location.href = resp.url || window.location.href;
		} finally {
			enviando = false;
		}
	}

	function montarCard() {
		const exercicioCard = card();
		if (!exercicioCard) return;
		const recallStep = document.getElementById("recall-step");
		const gabaritoStep = document.getElementById("gabarito-step");
		const respostaTexto = document.getElementById("resposta-texto");
		const answerForm = document.getElementById("answer-form");

		// A cada questão nova, traz o card de volta pro topo da tela.
		exercicioCard.scrollIntoView({ block: "start" });

		document.getElementById("revelar-btn").addEventListener("click", () => {
			document.getElementById("resposta-texto-field").value = respostaTexto.value;
			// A resposta escrita fica na tela, em leitura, junto do gabarito --
			// é exatamente na hora de comparar que ela é útil pra autoavaliação.
			// Só some se estiver em branco (não há o que comparar).
			recallStep.hidden = respostaTexto.value.trim() === "";
			respostaTexto.readOnly = true;
			document.getElementById("recall-hint").hidden = true;
			document.getElementById("recall-label").hidden = false;
			document.getElementById("revelar-wrap").hidden = true;
			gabaritoStep.hidden = false;
			// Rolar até o gabarito (que fica mais abaixo) empurrava a pergunta e
			// a resposta escrita pra fora da tela -- rola até o início do card
			// pra manter tudo visível.
			exercicioCard.scrollIntoView({ block: "start", behavior: "smooth" });
			locutor.aoRevelar();
		});

		exercicioCard.querySelectorAll(".quality-btn").forEach((btn) => {
			btn.addEventListener("click", (ev) => {
				ev.preventDefault();
				// Escurece antes de enviar: o botão fica marcado durante a
				// requisição, mostrando qual opção saiu.
				btn.classList.add("botao-acionado");
				document.getElementById("shortcut-field").value = btn.dataset.shortcut;
				enviarTrocando(answerForm);
			});
		});
	}

	function montarConteudo() {
		montarCard();

		document.querySelectorAll("#praticar-conteudo form[data-trocar]").forEach((form) => {
			form.addEventListener("submit", (ev) => {
				ev.preventDefault();
				enviarTrocando(form);
			});
		});

		const filtro = document.getElementById("tipos-filtro-form");
		if (filtro) {
			const caixas = filtro.querySelectorAll('input[name="tipos"]');
			const marcar = (valor) => caixas.forEach((caixa) => { caixa.checked = valor; });
			document.getElementById("tipos-marcar-todos").addEventListener("click", () => marcar(true));
			document.getElementById("tipos-limpar").addEventListener("click", () => marcar(false));
		}

		const limpar = document.getElementById("limpar-progresso-form");
		if (limpar) {
			limpar.addEventListener("submit", (ev) => {
				if (!confirm('Atenção: isso apaga TODO o seu progresso nesta aula (caixa, mesa, streak e histórico de respostas) e começa do zero. Não tem como desfazer. Continuar?')) {
					ev.preventDefault();
				}
			});
		}

		locutor.aoCarregarCard();
	}

	document.addEventListener("keydown", (ev) => {
		if (!gabaritoVisivel() || ev.target.tagName === "TEXTAREA" || ev.target.tagName === "INPUT") return;
		if (["1", "2"].includes(ev.key)) {
			const btn = document.querySelector('.quality-btn[data-shortcut="' + ev.key + '"]');
			if (btn) btn.click();
		}
	});

	// O navegador restaura sozinho a rolagem da página anterior, e fazia
	// isso depois do posicionamento do card, desfazendo-o: daí o "manual" e
	// a repetição no load, quando o documento inteiro já existe.
	if ("scrollRestoration" in history) history.scrollRestoration = "manual";
	window.addEventListener("load", () => {
		const exercicioCard = card();
		if (exercicioCard) exercicioCard.scrollIntoView({ block: "start" });
	});

	// --- comando de voz -------------------------------------------------------

	(() => {
		const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
		const toggleBtn = document.getElementById("voice-toggle-btn");
		const statusEl = document.getElementById("voice-status");
		if (!SpeechRecognition) {
			toggleBtn.disabled = true;
			statusEl.textContent = "Comando de voz não suportado neste navegador — use Chrome ou Edge.";
			return;
		}

		const STORAGE_KEY = "guia-praticar-voz-ativa";
		let recognition = null;
		let manualStop = false;
		let pausadoPelaLocucao = false;
		let voltarParaAguardando = null;
		let esperandoFinal = null;
		let retomar = null;
		// Resultado (índice em ev.results, dentro da sessão atual do
		// reconhecimento) que já virou comando: o parcial pode agir antes e o
		// final da MESMA fala chegar depois -- não pode repetir o comando.
		// Por índice, não pela frase: sem recarregar a página entre questões,
		// "lembrei" dito de novo na questão seguinte é outra fala, não repetição.
		let ultimoIndiceExecutado = -1;

		// O indicador fica junto dos botões (e não só no topo da página) porque
		// é olhando pra eles que se fala -- é ali que precisa dar pra ver se o
		// microfone está ocioso, captando ou interpretando o que ouviu.
		// Consultado a cada chamada: a troca de questão substitui os indicadores.
		function estado(nome, texto, voltarEm) {
			clearTimeout(voltarParaAguardando);
			document.querySelectorAll(".voz-indicador").forEach((el) => {
				el.hidden = nome === "off";
				el.dataset.estado = nome;
				el.textContent = texto;
			});
			if (voltarEm) {
				voltarParaAguardando = setTimeout(
					() =>
						pausadoPelaLocucao
							? estado("pausado", "🔊 lendo — microfone pausado")
							: estado("aguardando", "aguardando comando"),
					voltarEm
				);
			}
		}

		// Questão nova trouxe indicadores novos (vazios): mostra neles o
		// estado atual do microfone.
		document.addEventListener("praticar:novo-card", () => {
			if (!recognition) return;
			if (pausadoPelaLocucao) estado("pausado", "🔊 lendo — microfone pausado");
			else estado("aguardando", "aguardando comando");
		});

		// Só reconhece, não age: separado de `executar` porque a frase precisa
		// ser avaliada já no resultado parcial, pra decidir se vale esperar o
		// final. Devolve o comando, ou null quando nada casa.
		function identificar(fraseOriginal) {
			const frase = fraseOriginal.toLowerCase();
			const gabaritoAberto = gabaritoVisivel();

			// Releitura vem antes de tudo: "leia o gabarito de novo" não pode
			// cair no "revelar" só por conter "gabarito".
			const denovo = /novamente|de novo|repet/.test(frase);
			// \b do JS não entende acento ("lê"): separa por espaço.
			const leia = /(^|\s)(leia|ler|lê|le)(\s|$)/.test(frase);
			if (frase.includes("pergunta") && (denovo || leia)) return "ler-pergunta";
			if (gabaritoAberto && frase.includes("resposta") && (denovo || leia)) return "reler";
			if (denovo) return "reler";

			if (!gabaritoAberto) {
				// "revelar", "revelar gabarito" e só "gabarito" -- o motor corta
				// palavra curta com frequência, então vale aceitar as duas metades.
				if (frase.includes("revelar") || frase.includes("gabarito")) return "revelar";
				return null;
			}
			if (frase.includes("não lembrei") || frase.includes("nao lembrei") || frase.includes("errei")) return "1";
			if (frase.includes("lembrei") || frase.includes("acertei")) return "2";
			return null;
		}

		// Ponto único de execução, alimentado tanto pelo resultado final quanto
		// pelo parcial que o final não veio confirmar.
		function processar(frase, indice) {
			if (indice === ultimoIndiceExecutado) return;
			const comando = identificar(frase);
			if (comando) {
				ultimoIndiceExecutado = indice;
				estado("ok", "✓ " + executar(comando), 2500);
			} else {
				estado("falhou", '"' + frase + '" — nenhum comando, fale de novo', 4000);
			}
		}

		// Aciona o mesmo botão que o clique do mouse acionaria. Devolve o rótulo
		// mostrado no indicador.
		function executar(comando) {
			if (comando === "ler-pergunta") {
				locutor.falar("pergunta");
				return "lendo a pergunta";
			}
			if (comando === "reler") {
				const parte = gabaritoVisivel() ? "resposta" : "pergunta";
				locutor.falar(parte);
				return "lendo a " + parte + " de novo";
			}
			if (comando === "revelar") {
				document.getElementById("revelar-btn").click();
				return "revelar gabarito";
			}
			const btn = document.querySelector('.quality-btn[data-shortcut="' + comando + '"]');
			// Escurece o botão e espera um instante antes de enviar, senão a
			// questão troca antes de dar pra ver qual opção foi acionada. A
			// classe também barra um segundo reconhecimento da mesma frase, que
			// enfileiraria outro envio.
			if (btn && !btn.classList.contains("botao-acionado")) {
				btn.classList.add("botao-acionado");
				setTimeout(() => btn.click(), 450);
			}
			return comando === "1" ? "não lembrei" : "lembrei";
		}

		function comecarSessao() {
			ultimoIndiceExecutado = -1;
			recognition.start();
		}

		function iniciar() {
			recognition = new SpeechRecognition();
			recognition.lang = "pt-BR";
			recognition.continuous = true;
			// Resultados parciais existem aqui só pelo indicador: são o único
			// sinal confiável de que o microfone está captando agora (o evento
			// speechstart não dispara sempre no Chrome).
			recognition.interimResults = true;

			// Um ciclo de fala passa por speechstart (entrou som de voz),
			// speechend (parou de falar, o motor está transcrevendo) e result
			// (veio a transcrição) -- é essa sequência que o indicador espelha.
			recognition.onspeechstart = () => estado("captando", "ouvindo...");
			recognition.onspeechend = () => estado("interpretando", "interpretando...");
			recognition.onnomatch = () => estado("falhou", "não entendi", 2500);

			recognition.onresult = (ev) => {
				if (pausadoPelaLocucao) return;
				const indice = ev.results.length - 1;
				const ultimo = ev.results[indice];
				const frase = ultimo[0].transcript.trim();
				clearTimeout(esperandoFinal);

				if (!ultimo.isFinal) {
					// Vai chegando palavra a palavra enquanto se fala: mostra o
					// texto parcial (cortado, senão empurra os botões da linha).
					const parcial = frase.length > 40 ? "…" + frase.slice(-40) : frase;
					estado("captando", "ouvindo: " + parcial);
					// O resultado final nem sempre chega -- a sessão do Chrome
					// expira antes e o comando ficava só na tela, sem disparar.
					// Se o parcial já casa, age nele depois de um instante,
					// tempo de o final chegar e cancelar esta espera.
					if (identificar(frase)) {
						esperandoFinal = setTimeout(() => processar(frase, indice), 1200);
					}
					return;
				}
				processar(frase, indice);
			};
			recognition.onerror = (ev) => {
				if (ev.error === "not-allowed" || ev.error === "service-not-allowed") {
					statusEl.textContent = "Permissão de microfone negada.";
					manualStop = true;
					gravarPreferencia(STORAGE_KEY, false);
					toggleBtn.textContent = "🎙️ Ativar comando de voz";
					estado("off", "");
				} else if (ev.error !== "no-speech" && ev.error !== "aborted") {
					// no-speech é rotina (silêncio até o motor desistir e
					// reiniciar); aborted é a pausa da locução, de propósito.
					estado("falhou", "falha no microfone", 3000);
				}
			};
			recognition.onend = () => {
				// O navegador encerra o reconhecimento sozinho depois de um tempo
				// de silêncio; reinicia, a menos que o usuário tenha desligado
				// ou a locução esteja falando (aí quem religa é o fim dela). O
				// start vai adiado e protegido porque chamado na hora, dentro do
				// próprio onend, ele às vezes estoura InvalidStateError -- e aí o
				// microfone morria calado, com o botão ainda dizendo "desativar".
				if (manualStop || pausadoPelaLocucao) return;
				setTimeout(() => {
					if (manualStop || pausadoPelaLocucao || !recognition) return;
					try {
						comecarSessao();
					} catch (erro) {
						estado("falhou", "microfone parou — clique em desativar e ativar", 0);
					}
				}, 150);
			};
			if (pausadoPelaLocucao) {
				estado("pausado", "🔊 lendo — microfone pausado");
			} else {
				comecarSessao();
				estado("aguardando", "aguardando comando");
			}
			toggleBtn.textContent = "🔴 Desativar comando de voz";
			statusEl.textContent = 'Diga "revelar", "lembrei", "não lembrei" ou "leia novamente".';
		}

		function parar() {
			manualStop = true;
			clearTimeout(retomar);
			if (recognition) recognition.stop();
			recognition = null;
			toggleBtn.textContent = "🎙️ Ativar comando de voz";
			statusEl.textContent = "";
			estado("off", "");
		}

		// Locução falando: microfone parado (abort descarta o que estava
		// sendo ouvido -- era a própria locução). Volta ao fim dela, com uma
		// folga pro fim do som não entrar no começo da escuta.
		document.addEventListener("locucao:inicio", () => {
			pausadoPelaLocucao = true;
			clearTimeout(retomar);
			clearTimeout(esperandoFinal);
			if (!recognition) return;
			try {
				recognition.abort();
			} catch (erro) {
				// já estava parado
			}
			estado("pausado", "🔊 lendo — microfone pausado");
		});

		document.addEventListener("locucao:fim", () => {
			clearTimeout(retomar);
			retomar = setTimeout(() => {
				pausadoPelaLocucao = false;
				if (manualStop || !recognition) return;
				try {
					comecarSessao();
					estado("aguardando", "aguardando comando");
				} catch (erro) {
					// O abort ainda não terminou: o onend dele, que chega em
					// seguida, já vê a pausa desligada e religa sozinho.
				}
			}, 300);
		});

		toggleBtn.addEventListener("click", () => {
			if (recognition) {
				parar();
				gravarPreferencia(STORAGE_KEY, false);
			} else {
				manualStop = false;
				gravarPreferencia(STORAGE_KEY, true);
				iniciar();
			}
		});

		// A preferência liga o microfone de novo sozinho ao abrir a página --
		// a permissão do navegador já concedida evita pedir de novo.
		if (lerPreferencia(STORAGE_KEY)) {
			manualStop = false;
			iniciar();
		}
	})();

	// Por último: a primeira fala já precisa encontrar o comando de voz
	// ouvindo os eventos da locução, senão o microfone não pausa nela.
	locutor.iniciar();
	montarConteudo();
})();
