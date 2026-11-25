/* Página do guia (templates/guia.html, study/guia_pagina.py) -- o que ela
   tem além do layout do guia interativo (guia_interativo.js): narração com
   "ouvir esta seção", editar seção (admin) e os links antigos #secao-8-1. */
(function () {
	'use strict';
	var body = document.body;
	var lessonId = body.getAttribute('data-lesson-id');

	// Salto pelo mesmo caminho dos links da página (data-go), com o
	// deslocamento da barra e da trilha.
	function irPara(id) {
		var a = document.createElement('a');
		a.setAttribute('data-go', id);
		a.hidden = true;
		body.appendChild(a);
		a.click();
		a.remove();
	}

	// Link antigo de seção (dissertativas, guia consolidado): #secao-8-1.
	var m = /^secao-(\d+(?:-\d+)*)$/.exec(decodeURIComponent(location.hash.slice(1)));
	if (m) setTimeout(function () { irPara(m[1].replace(/-/g, '.')); }, 80);

	// ---------- narração: um mp3 só pra aula inteira, seções em sequência
	var player = document.getElementById('guia-player');
	if (player) {
		var playBtn = document.getElementById('guia-player-play');
		var statusEl = document.getElementById('guia-player-status');
		var secoes = Array.prototype.slice.call(document.querySelectorAll('[data-audio-start]')).map(function (el) {
			return {
				el: el.closest('.topic') || el,
				start: parseFloat(el.getAttribute('data-audio-start')),
				end: parseFloat(el.getAttribute('data-audio-end')),
				titulo: el.getAttribute('data-audio-titulo'),
			};
		});
		function seekTo(s) { player.currentTime = s; player.play(); }
		playBtn.addEventListener('click', function () { if (player.paused) player.play(); else player.pause(); });
		document.getElementById('guia-player-back15').addEventListener('click', function () {
			player.currentTime = Math.max(0, player.currentTime - 15);
		});
		document.getElementById('guia-player-fwd15').addEventListener('click', function () {
			player.currentTime = Math.min(player.duration || Infinity, player.currentTime + 15);
		});
		secoes.forEach(function (s) {
			var btn = s.el.querySelector('.guia-ouvir-secao');
			if (btn) btn.addEventListener('click', function (e) { e.stopPropagation(); seekTo(s.start); });
		});
		player.addEventListener('play', function () { playBtn.textContent = '⏸ pausar'; });
		player.addEventListener('pause', function () { playBtn.textContent = '▸ tocar'; });

		var atual = null;
		player.addEventListener('timeupdate', function () {
			var t = player.currentTime;
			var cur = secoes.find(function (s) { return t >= s.start && t < s.end; }) || null;
			if (cur === atual) return;
			if (atual) atual.el.classList.remove('guia-secao-atual');
			if (cur) {
				cur.el.classList.add('guia-secao-atual');
				irPara(cur.el.getAttribute('data-id'));
				statusEl.textContent = cur.titulo;
				if ('mediaSession' in navigator) {
					navigator.mediaSession.metadata = new MediaMetadata({
						title: cur.titulo,
						artist: body.getAttribute('data-guia-titulo'),
						album: 'Guia narrado — Estudos',
					});
				}
			}
			atual = cur;
		});
		if ('mediaSession' in navigator) {
			navigator.mediaSession.setActionHandler('play', function () { player.play(); });
			navigator.mediaSession.setActionHandler('pause', function () { player.pause(); });
			navigator.mediaSession.setActionHandler('seekbackward', function () {
				player.currentTime = Math.max(0, player.currentTime - 15);
			});
			navigator.mediaSession.setActionHandler('seekforward', function () {
				player.currentTime = Math.min(player.duration || Infinity, player.currentTime + 15);
			});
			navigator.mediaSession.setActionHandler('previoustrack', function () {
				var i = secoes.indexOf(atual);
				if (i > 0) seekTo(secoes[i - 1].start);
			});
			navigator.mediaSession.setActionHandler('nexttrack', function () {
				var i = secoes.indexOf(atual);
				if (i !== -1 && i < secoes.length - 1) seekTo(secoes[i + 1].start);
			});
		}
	}

	// ---------- editar seção (admin): o markdown cru da seção inteira, que
	// volta pro banco e remonta o guia_md. Salvou: recarrega, pra a página
	// renumerar e redividir os tópicos da seção.
	document.querySelectorAll('.guia-editar-secao').forEach(function (btn) {
		var secaoId = btn.getAttribute('data-secao-id');
		var art = btn.closest('.topic');
		var cap = art.closest('.chap');
		var fonte = art.querySelector('.guia-secao-fonte');
		var acoes = btn.parentNode;
		btn.addEventListener('click', function () {
			if (btn.hidden) return; // já em edição
			var escondidos = Array.prototype.slice.call(cap.querySelectorAll('.topic')).filter(function (t) { return t !== art; });
			var md = art.querySelector('.gp-md');
			if (md) escondidos.push(md);

			var textarea = document.createElement('textarea');
			textarea.className = 'gp-editor';
			textarea.value = fonte.value;
			textarea.rows = Math.min(40, Math.max(8, fonte.value.split('\n').length + 2));
			var salvar = document.createElement('button');
			salvar.type = 'button';
			salvar.className = 'gp-btn gp-btn-pri';
			salvar.textContent = 'Salvar';
			var cancelar = document.createElement('button');
			cancelar.type = 'button';
			cancelar.className = 'gp-btn';
			cancelar.textContent = 'Cancelar';
			var aviso = document.createElement('span');
			aviso.className = 'gp-mut';
			var linha = document.createElement('div');
			linha.className = 'gp-acoes';
			linha.append(salvar, cancelar, aviso);

			escondidos.forEach(function (el) { el.hidden = true; });
			btn.hidden = true;
			acoes.after(textarea, linha);
			textarea.focus();

			function fechar() {
				textarea.remove();
				linha.remove();
				escondidos.forEach(function (el) { el.hidden = false; });
				btn.hidden = false;
			}
			cancelar.addEventListener('click', fechar);
			salvar.addEventListener('click', function () {
				salvar.disabled = true;
				aviso.textContent = 'salvando...';
				var dados = new FormData();
				dados.append('corpo', textarea.value);
				fetch('/lessons/' + lessonId + '/guia/secoes/' + secaoId, { method: 'POST', body: dados })
					.then(function (resp) {
						if (!resp.ok) throw new Error('HTTP ' + resp.status);
						if (history.replaceState) history.replaceState(null, '', '#secao-' + art.getAttribute('data-id'));
						location.reload();
					})
					.catch(function (e) {
						// Sem fechar: fechar aqui perderia o texto digitado.
						aviso.textContent = 'não salvou (' + e.message + ') — o texto continua aí';
						salvar.disabled = false;
					});
			});
		});
	});
})();
