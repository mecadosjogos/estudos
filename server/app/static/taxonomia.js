// Taxonomia da matéria: árvore D3 colapsável, esquerda-para-direita, com
// zoom/pan manual (arrastar/rolar) e câmera automática que reenquadra o
// nó clicado + o que apareceu/sumiu a cada expandir/recolher. Substitui a
// renderização Mermaid estática (PLANO.md, 5b) -- Mermaid não tem colapso
// de sub-árvore em tempo de execução nem controle de câmera programável;
// d3.hierarchy + d3.tree + toggle children/_children é o padrão clássico
// pra isso.
(function () {
	var ROW_HEIGHT = 46; // espaço vertical entre nós irmãos (dá espaço pra rótulo de até 2 linhas)
	var LEVEL_WIDTH = 260; // espaço horizontal entre níveis -- rótulos jurídicos são frases longas
	var LABEL_WIDTH = 190; // largura do <div> do rótulo, onde o texto quebra linha

	function cssVar(name) {
		return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
	}

	var nextId = 0;
	function ensureId(d) {
		if (d.id === undefined) d.id = ++nextId;
		return d.id;
	}

	window.initTaxonomiaTree = function (container, rootsData) {
		container.innerHTML = "";

		if (!rootsData || !rootsData.length) {
			container.textContent = "Nenhuma aula desta matéria tem mapa de taxonomia gerado ainda.";
			return;
		}

		// d3.hierarchy exige uma raiz só -- se várias aulas geraram árvores
		// desconexas entre si, envolve numa raiz sintética invisível.
		var virtualRoot =
			rootsData.length === 1 ? rootsData[0] : { label: null, term_id: null, edge_label: null, children: rootsData };

		var root = d3.hierarchy(virtualRoot, function (d) {
			return d.children && d.children.length ? d.children : null;
		});
		root.x0 = 0;
		root.y0 = 0;
		// Começa tudo expandido -- mesmo comportamento que o Mermaid estático
		// já tinha (mostrava a árvore inteira de cara).

		var width = container.clientWidth || 900;
		var height = container.clientHeight || 600;

		var svg = d3.select(container).append("svg").attr("width", "100%").attr("height", "100%");

		var g = svg.append("g");

		var zoom = d3
			.zoom()
			.scaleExtent([0.2, 2])
			.on("zoom", function (event) {
				g.attr("transform", event.transform);
			});
		svg.call(zoom);

		var treeLayout = d3.tree().nodeSize([ROW_HEIGHT, LEVEL_WIDTH]);

		// Árvore esquerda-direita: profundidade vira eixo X da tela (d.y),
		// posição entre irmãos vira eixo Y da tela (d.x) -- técnica padrão
		// pra inverter o layout vertical default do d3.tree.
		var linkGen = d3
			.linkHorizontal()
			.x(function (d) {
				return d.y;
			})
			.y(function (d) {
				return d.x;
			});

		function toggle(d) {
			var expandindo;
			if (d.children) {
				d._children = d.children;
				d.children = null;
				expandindo = false;
			} else if (d._children) {
				d.children = d._children;
				d._children = null;
				expandindo = true;
			} else {
				return; // nó folha, nada a expandir/recolher
			}
			update(d);
			focusOn(d, expandindo);
		}

		function abrirVerbete(event, d) {
			event.stopPropagation();
			window.location.href = "/termos/" + d.data.term_id;
		}

		function update(source) {
			var treeData = treeLayout(root);
			var nodes = treeData.descendants().filter(function (d) {
				return d.data.label !== null; // pula a raiz sintética, se houver
			});
			var links = treeData.links().filter(function (d) {
				return d.source.data.label !== null;
			});

			// ---- arestas ----
			var link = g.selectAll("path.taxo-link").data(links, function (d) {
				return ensureId(d.target);
			});

			link
				.enter()
				.insert("path", "g")
				.attr("class", "taxo-link")
				.attr("d", function () {
					var o = { x: source.x0, y: source.y0 };
					return linkGen({ source: o, target: o });
				})
				.merge(link)
				.transition()
				.duration(400)
				.attr("d", linkGen);

			link
				.exit()
				.transition()
				.duration(400)
				.attr("d", function () {
					var o = { x: source.x, y: source.y };
					return linkGen({ source: o, target: o });
				})
				.remove();

			// ---- nós ----
			var node = g.selectAll("g.taxo-node").data(nodes, ensureId);

			var nodeEnter = node
				.enter()
				.append("g")
				.attr("class", "taxo-node")
				.attr("transform", "translate(" + source.y0 + "," + source.x0 + ")")
				.style("opacity", 0)
				.on("click", function (event, d) {
					toggle(d);
				});

			nodeEnter.append("circle").attr("class", "taxo-node-circle").attr("r", 6);

			var fo = nodeEnter
				.append("foreignObject")
				.attr("x", 12)
				.attr("y", -18)
				.attr("width", LABEL_WIDTH)
				.attr("height", 70);
			var labelDiv = fo.append("xhtml:div").attr("class", "taxo-label");
			labelDiv.append("xhtml:span").attr("class", "taxo-label-text").text(function (d) {
				return d.data.label;
			});
			labelDiv
				.filter(function (d) {
					return !!d.data.term_id;
				})
				.append("xhtml:a")
				.attr("class", "taxo-label-link")
				.attr("href", function (d) {
					return "/termos/" + d.data.term_id;
				})
				.text(" →")
				.on("click", abrirVerbete);

			var nodeUpdate = nodeEnter.merge(node);
			nodeUpdate
				.transition()
				.duration(400)
				.attr("transform", function (d) {
					return "translate(" + d.y + "," + d.x + ")";
				})
				.style("opacity", 1);
			nodeUpdate.select("circle.taxo-node-circle").attr("class", function (d) {
				var temFilhos = d.children || d._children;
				return "taxo-node-circle" + (temFilhos ? " taxo-node-circle-comfilhos" : "");
			});

			node
				.exit()
				.transition()
				.duration(400)
				.attr("transform", "translate(" + source.y + "," + source.x + ")")
				.style("opacity", 0)
				.remove();

			nodes.forEach(function (d) {
				d.x0 = d.x;
				d.y0 = d.y;
			});
		}

		// Enquadra um conjunto de nós na tela, com margem, animado.
		function fitTo(lista) {
			if (!lista.length) return;
			var depthMin = d3.min(lista, function (d) {
				return d.y;
			});
			var depthMax = d3.max(lista, function (d) {
				return d.y;
			});
			var breadthMin = d3.min(lista, function (d) {
				return d.x;
			});
			var breadthMax = d3.max(lista, function (d) {
				return d.x;
			});

			var pad = 90;
			var boxW = depthMax - depthMin + LABEL_WIDTH + pad;
			var boxH = breadthMax - breadthMin + pad;
			var cx = (depthMin + depthMax) / 2 + LABEL_WIDTH / 2;
			var cy = (breadthMin + breadthMax) / 2;

			var scale = Math.max(0.25, Math.min(1.4, Math.min(width / boxW, height / boxH)));
			var transform = d3.zoomIdentity.translate(width / 2, height / 2).scale(scale).translate(-cx, -cy);

			svg.transition().duration(500).call(zoom.transform, transform);
		}

		// Ao expandir: enquadra o nó clicado + tudo que apareceu com ele. Ao
		// recolher: enquadra o nó clicado + a origem (o pai), pra manter o
		// contexto de onde ele estava.
		function focusOn(d, expandindo) {
			if (expandindo) {
				fitTo(d.descendants());
			} else if (d.parent) {
				fitTo([d, d.parent]);
			} else {
				fitTo([d]);
			}
		}

		update(root);
		// Foco inicial: raiz e primeiro nível, mesmo critério de "expandir".
		focusOn(root, true);
	};
})();
