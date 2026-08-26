// Rede de conceitos (grafo livre de Termos + Assuntos). Recebe {nodes, edges}
// já calculados no servidor (network/cooccurrence.py) e monta um vis.Network
// -- a física posiciona os nós sozinha, nenhuma coordenada calculada na mão.
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
				title: (n.tipo === "assunto" ? "Assunto: " : "Termo: ") + n.label,
			};
		});
	}

	function toVisEdges(edges) {
		var maxPeso = edges.reduce(function (m, e) { return Math.max(m, e.peso); }, 1);
		return edges.map(function (e, i) {
			var discriminacao = e.origem === "discriminacao";
			return {
				id: i,
				from: e.a,
				to: e.b,
				dashes: discriminacao,
				width: discriminacao ? 2 : Math.max(1, (e.peso / maxPeso) * 6),
				color: discriminacao
					? { color: cssVar("--accent"), opacity: 0.9 }
					: { color: cssVar("--text-muted"), opacity: Math.min(0.9, 0.25 + (e.peso / maxPeso) * 0.65) },
				title: e.rotulo || (discriminacao ? "distinção" : "coocorrência (peso " + e.peso + ")"),
			};
		});
	}

	// container: elemento DOM. graph: {nodes, edges}. subjectColors: {subject_id: cor}.
	window.renderRede = function (container, graph, subjectColors) {
		container.innerHTML = "";
		if (!graph.nodes.length) {
			container.textContent = "Ainda não há termos ou assuntos suficientes ligados aqui pra desenhar uma rede.";
			return null;
		}
		var nodes = new vis.DataSet(toVisNodes(graph.nodes, subjectColors || {}));
		var edges = new vis.DataSet(toVisEdges(graph.edges));
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
		network.on("click", function (params) {
			if (!params.nodes.length) return;
			var partes = String(params.nodes[0]).split(":");
			var tipo = partes[0];
			var rawId = partes[1];
			if (tipo === "term") window.location.href = "/termos/" + rawId;
			else if (tipo === "assunto") window.location.href = "/assuntos/" + rawId;
		});
		return network;
	};
})();
