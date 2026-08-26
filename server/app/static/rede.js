// Rede de conceitos. Recebe {nodes, edges} já calculados no servidor
// (network/graph.py) e monta um vis.Network -- a física posiciona os nós
// sozinha, nenhuma coordenada calculada na mão. Uma legenda com checkbox
// por tipo de nó e por origem de aresta explica cada forma/traço E filtra
// o que aparece, tudo client-side (sem round-trip: o servidor já manda o
// grafo inteiro). Clique num nó destaca a vizinhança e abre um painel com
// a origem em vez de navegar direto; navegar é uma ação explícita no
// painel ("abrir →").
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

	// Termo que participa de pelo menos uma aresta de taxonomia vira
	// triângulo em vez de círculo -- sinal visual de "isso está na
	// hierarquia que o professor desenhou" (triângulo evoca a estrutura em
	// árvore, diferente do círculo solto), a mesma distinção que motivou a
	// taxonomia virar a fonte principal (PLANO.md, 5b). É sobre a aresta
	// bruta do grafo inteiro, não sobre o que a legenda está mostrando no
	// momento -- desmarcar "Taxonomia" esconde a linha, não desfaz o
	// triângulo, porque o fato de o termo pertencer à hierarquia não muda.
	function idsNaTaxonomia(edges) {
		var ids = {};
		edges.forEach(function (e) {
			if (e.origem === "taxonomia") {
				ids[e.a] = true;
				ids[e.b] = true;
			}
		});
		return ids;
	}

	function formaDoNo(node, taxonomiaIds) {
		if (node.tipo === "assunto") return "diamond";
		return taxonomiaIds[node.id] ? "triangle" : "dot";
	}

	function toVisNodes(nodes, subjectColors, taxonomiaIds) {
		return nodes.map(function (n) {
			var cor = nodeColor(n, subjectColors);
			return {
				id: n.id,
				label: n.label,
				shape: formaDoNo(n, taxonomiaIds),
				size: n.tipo === "assunto" ? 16 : 10,
				color: { background: cor, border: cor, highlight: { background: cor, border: cssVar("--text") } },
				font: { color: cssVar("--text") },
			};
		});
	}

	var NODE_TIPO_INFO = {
		term: { label: "Termo", sample: "dot" },
		assunto: { label: "Assunto", sample: "diamond" },
	};

	// Taxonomia é a fonte principal (PLANO.md, 5b) -- só ela e discriminação
	// vêm ligadas por padrão. Assunto pode explodir sozinho quando uma aula
	// cobre muitos assuntos de uma vez (par-a-par: 15 assuntos = 105
	// arestas só entre eles) e afogava a taxonomia por baixo; vira opt-in,
	// igual coocorrência.
	var EDGE_ORIGEM_INFO = {
		taxonomia: { label: "Taxonomia (estrutura da aula)", defaultOn: true },
		discriminacao: { label: "Distinção", defaultOn: true },
		assunto: { label: "Assunto cobre os dois (pode ficar denso)", defaultOn: false },
		coocorrencia: { label: "Coocorrência de texto (mais denso)", defaultOn: false },
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

	var ORIGEM_LABEL = {
		taxonomia: "taxonomia da aula",
		discriminacao: "distinção",
		assunto: "assunto",
		coocorrencia: "coocorrência de texto",
	};

	function abrirUrl(nodeId) {
		var partes = String(nodeId).split(":");
		return partes[0] === "term" ? "/termos/" + partes[1] : "/assuntos/" + partes[1];
	}

	// Monta a legenda (explica forma/traço) e devolve o estado de filtro
	// vivo -- cada checkbox already reflete o default (taxonomia/
	// discriminação/assunto ligados, coocorrência desligada).
	function buildLegend(container, onChange) {
		var state = { nodeTipos: {}, edgeOrigens: {} };
		if (!container) {
			Object.keys(NODE_TIPO_INFO).forEach(function (t) { state.nodeTipos[t] = true; });
			Object.keys(EDGE_ORIGEM_INFO).forEach(function (o) { state.edgeOrigens[o] = EDGE_ORIGEM_INFO[o].defaultOn; });
			return state;
		}

		container.innerHTML = "";
		container.className = "rede-legend";

		function addItem(group, checked, sampleClass, texto, onToggle) {
			var label = document.createElement("label");
			label.className = "rede-legend-item";
			var checkbox = document.createElement("input");
			checkbox.type = "checkbox";
			checkbox.checked = checked;
			checkbox.addEventListener("change", function () {
				onToggle(checkbox.checked);
				onChange();
			});
			var sample = document.createElement("span");
			sample.className = "rede-legend-sample " + sampleClass;
			label.appendChild(checkbox);
			label.appendChild(sample);
			label.appendChild(document.createTextNode(" " + texto));
			group.appendChild(label);
		}

		// Só explica, não filtra -- quadrado é uma variação de forma dentro
		// do próprio tipo "Termo" (mesmo checkbox acima liga/desliga os
		// dois), não uma categoria à parte.
		function addNota(group, sampleClass, texto) {
			var span = document.createElement("span");
			span.className = "rede-legend-item rede-legend-item-nota";
			var sample = document.createElement("span");
			sample.className = "rede-legend-sample " + sampleClass;
			span.appendChild(sample);
			span.appendChild(document.createTextNode(" " + texto));
			group.appendChild(span);
		}

		var nodesGroup = document.createElement("div");
		nodesGroup.className = "rede-legend-group";
		Object.keys(NODE_TIPO_INFO).forEach(function (tipo) {
			state.nodeTipos[tipo] = true;
			var info = NODE_TIPO_INFO[tipo];
			addItem(nodesGroup, true, "rede-legend-sample-" + info.sample, info.label, function (checked) {
				state.nodeTipos[tipo] = checked;
			});
		});
		addNota(nodesGroup, "rede-legend-sample-triangle", "Termo também na taxonomia (hierarquia)");
		container.appendChild(nodesGroup);

		var edgesGroup = document.createElement("div");
		edgesGroup.className = "rede-legend-group";
		Object.keys(EDGE_ORIGEM_INFO).forEach(function (origem) {
			var info = EDGE_ORIGEM_INFO[origem];
			state.edgeOrigens[origem] = info.defaultOn;
			addItem(
				edgesGroup,
				info.defaultOn,
				"rede-legend-sample-linha rede-legend-sample-" + origem,
				info.label,
				function (checked) {
					state.edgeOrigens[origem] = checked;
				}
			);
		});
		container.appendChild(edgesGroup);

		return state;
	}

	// container: elemento DOM do grafo. graph: {nodes, edges}. subjectColors:
	// {subject_id: cor}. infoContainer: painel de clique. legendContainer:
	// onde desenhar a legenda/filtro (opcional, mas sem ela não dá pra
	// desligar nenhuma camada).
	window.renderRede = function (container, graph, subjectColors, infoContainer, legendContainer) {
		container.innerHTML = "";
		if (infoContainer) infoContainer.innerHTML = "";
		if (legendContainer) legendContainer.innerHTML = "";
		if (!graph.nodes.length) {
			container.textContent = "Ainda não há taxonomia, assunto ou discriminação suficiente ligados aqui pra desenhar uma rede.";
			return null;
		}

		var nodeTipoById = {};
		graph.nodes.forEach(function (n) { nodeTipoById[n.id] = n.tipo; });

		var nodesData = toVisNodes(graph.nodes, subjectColors || {}, idsNaTaxonomia(graph.edges));
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

		function edgePassaFiltro(filtro, e) {
			return filtro.edgeOrigens[e._origem] && filtro.nodeTipos[nodeTipoById[e.from]] && filtro.nodeTipos[nodeTipoById[e.to]];
		}

		// Recalcula visibilidade a partir só do filtro (legenda) -- também
		// serve pra limpar um destaque de vizinhança, já que o resultado é
		// sempre "tudo que passa no filtro, com opacidade cheia".
		function atualizarVisibilidade() {
			nodes.update(nodesData.map(function (n) {
				return { id: n.id, hidden: !filtro.nodeTipos[nodeTipoById[n.id]], opacity: 1 };
			}));
			edges.update(edgesData.map(function (e) {
				return { id: e.id, hidden: !edgePassaFiltro(filtro, e) };
			}));
		}

		function highlightNeighborhood(nodeId) {
			var connectedNodes = {};
			network.getConnectedNodes(nodeId).concat([nodeId]).forEach(function (id) { connectedNodes[id] = true; });
			var connectedEdges = {};
			network.getConnectedEdges(nodeId).forEach(function (id) { connectedEdges[id] = true; });

			nodes.update(nodesData.map(function (n) {
				if (!filtro.nodeTipos[nodeTipoById[n.id]]) return { id: n.id, hidden: true };
				return { id: n.id, hidden: false, opacity: connectedNodes[n.id] ? 1 : 0.15 };
			}));
			edges.update(edgesData.map(function (e) {
				return { id: e.id, hidden: !(edgePassaFiltro(filtro, e) && connectedEdges[e.id]) };
			}));
		}

		var filtro = buildLegend(legendContainer, atualizarVisibilidade);
		atualizarVisibilidade();

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
			atualizarVisibilidade();
			setInfo("");
		});

		return network;
	};

	// container: elemento DOM do grafo. graph: {nodes, edges} já pronto.
	// subjectColors: {subject_id: cor}. infoContainer/legendContainer:
	// opcionais.
	window.initRede = function (opts) {
		window.renderRede(opts.container, opts.graph, opts.subjectColors, opts.infoContainer, opts.legendContainer);
	};
})();
