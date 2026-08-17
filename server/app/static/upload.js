/* Upload em chunks com retomada automática (PLANO.md, fase 3).
 *
 * Cada arquivo escolhido vira uma aula própria por padrão. Dar o mesmo número
 * de "grupo" a dois ou mais arquivos os junta numa aula única, na ordem dada
 * pelo campo "ordem" — é assim que o intervalo (gravação partida em dois) se
 * declara. upload_id é derivado do nome+tamanho+data de modificação do
 * arquivo, então re-selecionar o mesmo arquivo depois de a aba fechar retoma
 * do chunk onde parou em vez de reenviar tudo.
 */

const CHUNK_SIZE = 4 * 1024 * 1024;

function hashKey(str) {
	let h1 = 0x811c9dc5;
	let h2 = 0x1000193;
	for (let i = 0; i < str.length; i++) {
		const c = str.charCodeAt(i);
		h1 = (h1 ^ c) * 0x01000193;
		h2 = (h2 ^ c) * 0x811c9dc5;
	}
	const hex = (n) => (n >>> 0).toString(16).padStart(8, "0");
	return "u" + hex(h1) + hex(h2);
}

function formatBytes(bytes) {
	if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
	return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

function todayIso() {
	return new Date().toISOString().slice(0, 10);
}

function initUploadPage({ subjects, subjectLabels }) {
	const state = {
		files: [], // { file, key, grupo, ordem, statusEl, progressText }
		groups: {}, // grupo -> { subjectId, titulo, data }
		nextGrupo: 1,
	};

	const fileInput = document.getElementById("file-input");
	const fileRows = document.getElementById("file-rows");
	const groupBoxes = document.getElementById("group-boxes");
	const submitCard = document.getElementById("submit-card");
	const submitButton = document.getElementById("submit-button");
	const overallStatus = document.getElementById("overall-status");

	fileInput.addEventListener("change", () => {
		for (const file of fileInput.files) {
			const key = hashKey(`${file.name}|${file.size}|${file.lastModified}`);
			if (state.files.some((f) => f.key === key)) continue;
			const grupo = state.nextGrupo++;
			state.files.push({ file, key, grupo, ordem: 1, status: "pendente" });
			state.groups[grupo] = {
				subjectId: subjects[0],
				titulo: file.name.replace(/\.[^.]+$/, ""),
				data: todayIso(),
			};
		}
		fileInput.value = "";
		render();
	});

	function render() {
		renderFileRows();
		renderGroupBoxes();
		submitCard.style.display = state.files.length ? "block" : "none";
	}

	function renderFileRows() {
		fileRows.innerHTML = "";
		if (!state.files.length) return;

		const card = document.createElement("div");
		card.className = "card";
		const heading = document.createElement("h2");
		heading.textContent = "Arquivos";
		card.appendChild(heading);

		const list = document.createElement("ul");
		list.className = "timeline";

		for (const entry of state.files) {
			const li = document.createElement("li");

			const name = document.createElement("span");
			name.textContent = entry.file.name;
			li.appendChild(name);

			const size = document.createElement("span");
			size.className = "muted";
			size.textContent = formatBytes(entry.file.size);
			li.appendChild(size);

			li.appendChild(numberField(
				"Grupo",
				entry.grupo,
				"Arquivos com o mesmo número de grupo viram uma aula só (o caso do intervalo). Deixe cada um com um número diferente para virarem aulas separadas — é o normal.",
				(value) => {
					entry.grupo = value;
					if (!(value in state.groups)) {
						state.groups[value] = { subjectId: subjects[0], titulo: entry.file.name.replace(/\.[^.]+$/, ""), data: todayIso() };
					}
					renderGroupBoxes();
				}
			));

			li.appendChild(numberField(
				"Ordem",
				entry.ordem,
				"Dentro do mesmo grupo, define qual arquivo toca primeiro: 1 = antes do intervalo, 2 = depois.",
				(value) => {
					entry.ordem = value;
				}
			));

			const status = document.createElement("span");
			status.className = "muted";
			status.style.marginLeft = "auto";
			status.textContent = entry.status;
			entry.statusEl = status;
			li.appendChild(status);

			list.appendChild(li);
		}

		card.appendChild(list);
		fileRows.appendChild(card);
	}

	function numberField(labelText, value, tooltip, onChange) {
		const label = document.createElement("label");
		label.style.display = "inline-flex";
		label.style.alignItems = "center";
		label.style.gap = "0.3rem";
		label.style.marginBottom = "0";
		label.title = tooltip;
		label.textContent = labelText;

		const help = document.createElement("span");
		help.textContent = " ⓘ";
		help.className = "muted";
		label.appendChild(help);

		const input = document.createElement("input");
		input.type = "number";
		input.min = "1";
		input.value = value;
		input.title = tooltip;
		input.style.width = "4rem";
		input.style.minHeight = "auto";
		input.addEventListener("change", () => onChange(parseInt(input.value, 10) || 1));

		label.appendChild(input);
		return label;
	}

	function renderGroupBoxes() {
		groupBoxes.innerHTML = "";
		const grupoNumbers = [...new Set(state.files.map((f) => f.grupo))].sort((a, b) => a - b);

		for (const grupo of grupoNumbers) {
			const filesInGroup = state.files.filter((f) => f.grupo === grupo).sort((a, b) => a.ordem - b.ordem);
			const cfg = state.groups[grupo];

			const card = document.createElement("div");
			card.className = "card";

			const heading = document.createElement("h2");
			heading.textContent = `Aula (grupo ${grupo}) — ${filesInGroup.map((f) => f.file.name).join(" + ")}`;
			card.appendChild(heading);

			const subjectLabel = document.createElement("label");
			subjectLabel.textContent = "Matéria";
			const subjectSelect = document.createElement("select");
			subjects.forEach((id, i) => {
				const option = document.createElement("option");
				option.value = id;
				option.textContent = subjectLabels[i];
				if (id === cfg.subjectId) option.selected = true;
				subjectSelect.appendChild(option);
			});
			subjectSelect.addEventListener("change", () => (cfg.subjectId = parseInt(subjectSelect.value, 10)));
			subjectLabel.appendChild(document.createElement("br"));
			subjectLabel.appendChild(subjectSelect);
			card.appendChild(subjectLabel);

			const tituloLabel = document.createElement("label");
			tituloLabel.textContent = "Título";
			const tituloInput = document.createElement("input");
			tituloInput.type = "text";
			tituloInput.value = cfg.titulo;
			tituloInput.addEventListener("change", () => (cfg.titulo = tituloInput.value));
			tituloLabel.appendChild(document.createElement("br"));
			tituloLabel.appendChild(tituloInput);
			card.appendChild(tituloLabel);

			const dataLabel = document.createElement("label");
			dataLabel.textContent = "Data";
			const dataInput = document.createElement("input");
			dataInput.type = "date";
			dataInput.value = cfg.data;
			dataInput.addEventListener("change", () => (cfg.data = dataInput.value));
			dataLabel.appendChild(document.createElement("br"));
			dataLabel.appendChild(dataInput);
			card.appendChild(dataLabel);

			groupBoxes.appendChild(card);
		}
	}

	submitButton.addEventListener("click", async () => {
		submitButton.disabled = true;
		const grupoNumbers = [...new Set(state.files.map((f) => f.grupo))].sort((a, b) => a - b);

		for (const grupo of grupoNumbers) {
			const cfg = state.groups[grupo];
			overallStatus.textContent = `Criando aula "${cfg.titulo}"...`;

			const form = new FormData();
			form.set("subject_id", cfg.subjectId);
			form.set("titulo", cfg.titulo);
			form.set("data", cfg.data);
			const lessonResponse = await fetch("/api/lessons", { method: "POST", body: form, credentials: "same-origin" });
			const { id: lessonId } = await lessonResponse.json();

			const filesInGroup = state.files.filter((f) => f.grupo === grupo).sort((a, b) => a.ordem - b.ordem);
			for (const entry of filesInGroup) {
				await uploadFile(entry, lessonId);
			}
		}

		overallStatus.textContent = "Tudo enviado.";
		submitButton.disabled = false;
	});

	async function uploadFile(entry, lessonId) {
		const { file, key, ordem, statusEl } = entry;
		const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

		entry.status = "iniciando...";
		if (statusEl) statusEl.textContent = entry.status;

		const initResponse = await fetch("/api/uploads/init", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			credentials: "same-origin",
			body: JSON.stringify({
				upload_id: key,
				lesson_id: lessonId,
				ordem,
				filename: file.name,
				total_chunks: totalChunks,
			}),
		});
		const { received_chunks: received } = await initResponse.json();
		const receivedSet = new Set(received);

		for (let index = 0; index < totalChunks; index++) {
			if (receivedSet.has(index)) continue;

			entry.status = `${index + 1}/${totalChunks} (${Math.round(((index + 1) / totalChunks) * 100)}%)`;
			if (statusEl) statusEl.textContent = entry.status;

			const start = index * CHUNK_SIZE;
			const blob = file.slice(start, start + CHUNK_SIZE);
			await putChunkWithRetry(key, index, blob);
		}

		await fetch(`/api/uploads/${key}/complete`, { method: "POST", credentials: "same-origin" });
		entry.status = "concluído";
		if (statusEl) statusEl.textContent = entry.status;
	}

	async function putChunkWithRetry(uploadId, index, blob) {
		let attempt = 0;
		while (true) {
			try {
				const response = await fetch(`/api/uploads/${uploadId}/chunks/${index}`, {
					method: "PUT",
					credentials: "same-origin",
					headers: { "Content-Type": "application/octet-stream" },
					body: blob,
				});
				if (response.ok) return;
				if (response.status >= 400 && response.status < 500) {
					throw new Error(`Envio recusado (${response.status}) — corrija e tente de novo`);
				}
				// 5xx: cai no retry abaixo
			} catch (err) {
				if (err.message && err.message.startsWith("Envio recusado")) throw err;
				// erro de rede: espera reconectar antes de tentar de novo
			}

			attempt++;
			const wait = Math.min(30000, 1000 * 2 ** Math.min(attempt, 5));
			await new Promise((resolve) => setTimeout(resolve, wait));
		}
	}

	render();
}
