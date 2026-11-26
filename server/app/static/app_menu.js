/* Gaveta do menu do app (base.html): abre no ☰, fecha no ✕, tocando
   fora ou com Esc. No computador (≥1100px) a gaveta fica sempre aberta
   pelo CSS e o ☰ some -- nada a fazer aqui. */
(function () {
	'use strict';
	var side = document.getElementById('appSide');
	var scrim = document.getElementById('appScrim');
	var abrir = document.getElementById('appMenu');
	var fechar = document.getElementById('appClose');
	if (!side || !abrir) return;
	function open() {
		side.classList.add('aberto');
		scrim.hidden = false;
		abrir.setAttribute('aria-expanded', 'true');
		var atual = side.querySelector('.app-link.atual') || side.querySelector('.app-link');
		if (atual) atual.focus({ preventScroll: true });
	}
	function close() {
		side.classList.remove('aberto');
		scrim.hidden = true;
		abrir.setAttribute('aria-expanded', 'false');
	}
	abrir.addEventListener('click', open);
	if (fechar) fechar.addEventListener('click', close);
	scrim.addEventListener('click', close);
	document.addEventListener('keydown', function (e) {
		if (e.key === 'Escape' && side.classList.contains('aberto')) { close(); abrir.focus(); }
	});
})();
