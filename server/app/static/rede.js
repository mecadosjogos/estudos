// Rede de conceitos. Recebe {nodes, edges} já calculados no servidor
// (network/graph.py) e monta um vis.Network -- a física posiciona os nós
// sozinha, nenhuma coordenada calculada na mão. Clique num nó destaca a
// vizinhança e abre um painel com a origem em vez de navegar direto;
// navegar é uma ação explícita no painel ("abrir →"), pra não perder o
// grafo com um clique errado quando ele fica com muitos nós.
(function () {
	function cssVar(name) {
		return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
	}

	function nodeColor(node, subjectColors) {
		if (node.subject_ids.length >= 2) return cssVar("--accent");
		if (node.subject_ids.length === 1 && subjectColors[node.subject_ids[0]]) {
			return subjectColors[node.subject_ids[0]];
		}
		return cssVar("--border");
	}

	function toVisNodes(nodes, subjectColors) {
		return nodes.map(function (n) {
			var cor = nodeColor(n, subjectColors);
			return {
				id: n.id,
				label: n.label,
				shape: n.tipo === "assunto" ? "diamond" : "dot",
				size: n.tipo === "assunto" ? 16 : 10,
				color: { background: cor, border: cor, highlight: { background: cor, border: cssVar("--text") } },
				font: { color: cssVar("--text") },
			};
		});
	}

	var ORIGEM_LABEL = {
		taxonomia: "taxonomia da aula",
		discriminacao: "distinção",
		assunto: "assunto",
		coocorrencia: "coocorrência de texto",
	};

	function toVisEdges(edges) {
		var maxPeso = edges.reduce(function (m, e) { return Math.max(m, e.peso); }, 1);
		return edges.map(function (e, i) {
			var discriminacao = e.origem === "discriminacao";
			return {
				id: i,
				from: e.a,
				to: e.b,
				dashes: discriminacao,
				arrows: e.direcionado ? "to" : undefined,
				width: discriminacao ? 2 : Math.max(1, (e.peso / maxPeso) * 6),
				color: discriminacao
					? { color: cssVar("--accent"), opacity: 0.9 }
					: { color: cssVar("--text-muted"), opacity: Math.min(0.9, 0.35 + (e.peso / maxPeso) * 0.55) },
				_origem: e.origem,
				_rotulo: e.rotulo,
				_lessonIds: e.lesson_ids || [],
			};
		});
	}

	function abrirUrl(nodeId) {
		var partes = String(nodeId).split(":");
		return partes[0] === "term" ? "/termos/" + partes[1] : "/assuntos/" + partes[1];
	}

	// container: elemento DOM do grafo. graph: {nodes, edges}. subjectColors:
	// {subject_id: cor}. infoContainer: elemento DOM onde mostrar o painel
	// de clique (opcional, mas sem ele clicar não abre nada).
	window.renderRede = function (container, graph, subjectColors, infoContainer) {
		container.innerHTML = "";
		if (infoContainer) infoContainer.innerHTML = "";
		if (!graph.nodes.length) {
			container.textContent = "Ainda não há taxonomia, assunto ou discriminação suficiente ligados aqui pra desenhar uma rede.";
			return null;
		}

		var nodesData = toVisNodes(graph.nodes, subjectColors || {});
		var edgesData = toVisEdges(graph.edges);
		var nodes = new vis.DataSet(nodesData);
		var edges = new vis.DataSet(edgesData);

		var network = new vis.Network(
			container,
			{ nodes: nodes, edges: edges },
			{
				physics: {
					stabilization: { iterations: 150 },
					barnesHut: { gravitationalConstant: -4000, springLength: 120, springConstant: 0.02 },
				},
				interaction: { hover: true, tooltipDelay: 150 },
			}
		);

		function setInfo(html) {
			if (infoContainer) infoContainer.innerHTML = html;
		}

		function clearHighlight() {
			nodes.update(nodesData.map(function (n) { return { id: n.id, opacity: 1 }; }));
			edges.update(edgesData.map(function (e) { return { id: e.id, hidden: false }; }));
		}

		function highlightNeighborhood(nodeId) {
			var connectedNodes = {};
			network.getConnectedNodes(nodeId).concat([nodeId]).forEach(function (id) { connectedNodes[id] = true; });
			var connectedEdges = {};
			network.getConnectedEdges(nodeId).forEach(function (id) { connectedEdges[id] = true; });

			nodes.update(nodesData.map(function (n) {
				return { id: n.id, opacity: connectedNodes[n.id] ? 1 : 0.15 };
			}));
			edges.update(edgesData.map(function (e) {
				return { id: e.id, hidden: !connectedEdges[e.id] };
			}));
		}

		network.on("click", function (params) {
			if (params.nodes.length) {
				var nodeId = params.nodes[0];
				var node = graph.nodes.filter(function (n) { return n.id === nodeId; })[0];
				highlightNeighborhood(nodeId);
				setInfo(
					"<p><strong>" + node.label + "</strong> (" + (node.tipo === "assunto" ? "assunto" : "termo") + ")" +
					' — <a href="' + abrirUrl(nodeId) + '">abrir →</a></p>'
				);
				return;
			}
			if (params.edges.length) {
				var edgeData = edgesData[params.edges[0]];
				var links = edgeData._lessonIds
					.map(function (lid) { return '<a href="/lessons/' + lid + '">▸ ver aula ' + lid + "</a>"; })
					.join(" · ");
				setInfo(
					"<p><strong>" + (ORIGEM_LABEL[edgeData._origem] || edgeData._origem) + "</strong>" +
					(edgeData._rotulo ? " — " + edgeData._rotulo : "") +
					(links ? "<br>" + links : "") + "</p>"
				);
				return;
			}
			clearHighlight();
			setInfo("");
		});

		return network;
	};

	// Amarra um grafo com toggle de camada opcional (checkbox "+ coocorrência
	// bruta") sem round-trip ao servidor -- os dois JSONs já vêm prontos.
	// opts: { container, infoContainer, checkbox, graphs: {base, comCoocorrencia}, subjectColors }
	window.initRede = function (opts) {
		function render() {
			var atual = opts.checkbox && opts.checkbox.checked ? opts.graphs.comCoocorrencia : opts.graphs.base;
			window.renderRede(opts.container, atual, opts.subjectColors, opts.infoContainer);
		}
		render();
		if (opts.checkbox) {
			opts.checkbox.addEventListener("change", render);
		}
	};
})();
