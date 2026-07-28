const knowledge = [
  {
    keys: ["banca", "anac", "ppa", "voos"],
    question: "Quantos voos o aluno pode fazer sem concluir a banca da ANAC para PPA?",
    answer: `<p>Na SAFE, o aluno de PPA pode realizar <strong>até 6 missões sem concluir a banca da ANAC</strong>, correspondentes à progressão da <strong>PS01 até a PS06</strong>.</p><div class="answer-highlight"><strong>Antes de iniciar a PS07</strong>, o aluno deve ter concluído a banca teórica da ANAC com aprovação.</div><p>Em caso de repetição, a regra considera a <strong>fase da instrução</strong> — antes da PS07 — e não uma quantidade absoluta de decolagens.</p>`,
    source: "B-OPS-065 — Requisitos do Curso de PPA",
    detail: "Regra prática: banca concluída antes da missão PS07 · Documento vigente",
    relations: [["PROGRAMA DE INSTRUÇÃO", "PPAP001K — Piloto Privado", "Revisão K · 01/02/2026"], ["MARCO DA PROGRESSÃO", "PS07", "Banca obrigatória antes desta missão"], ["REQUISITO POSTERIOR", "Primeiro voo solo", "Exige aprovação teórica e demais requisitos"]]
  },
  {
    keys: ["slots", "seguidos", "cinco", "5"],
    question: "O aluno pode voar cinco slots seguidos?",
    answer: `<p>Esta regra ainda precisa ser confirmada na fonte vigente antes de uma decisão operacional.</p><div class="answer-highlight"><strong>Conduta recomendada:</strong> consulte a regra de agendamento aplicável à base e ao curso do aluno, considerando também jornada, disponibilidade do instrutor e limitações operacionais.</div>`,
    source: "Base em revisão — regras de agendamento e slots",
    detail: "Resposta ainda não promovida como conhecimento confirmado",
    relations: [["TEMA", "Agendamento de voos", "Regras por base"], ["DEPENDÊNCIA", "Jornada do instrutor", "Verificação necessária"], ["DEPENDÊNCIA", "Limites do programa", "Curso e fase do aluno"]]
  },
  {
    keys: ["experiência", "recente", "noturna", "renovação"],
    question: "Como funciona a renovação da experiência recente noturna?",
    answer: `<p>Quando o piloto está há mais de 90 dias sem voar, uma adaptação <strong>noturna</strong> renova a experiência recente noturna e também a <strong>diurna</strong>.</p><div class="answer-highlight">Uma adaptação somente <strong>diurna</strong> renova apenas a experiência diurna.</div>`,
    source: "B-OPS-054/2024 — Renovação da experiência recente",
    detail: "Relação operacional validada na base de conhecimento",
    relations: [["CONDIÇÃO", "Mais de 90 dias sem voar", "Experiência recente vencida"], ["ADAPTAÇÃO DIURNA", "Renova experiência diurna", "Não renova a noturna"], ["ADAPTAÇÃO NOTURNA", "Renova diurna e noturna", "Relação cumulativa"]]
  }
];

const graphIndex = window.SAFE_KNOWLEDGE_INDEX || { meta: {}, claims: [], documents: [] };
const API_URL = window.SAFE_CCO_API_URL || `${window.location.origin}/api/ask`;
const nativeFetch = window.fetch.bind(window);
let currentUser = null;
let csrfToken = "";
let portalBootstrapped = false;
const hasRole = (...roles) => Boolean(currentUser && roles.includes(currentUser.role));

async function apiFetch(url, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}) };
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const response = await nativeFetch(url, { ...options, headers, credentials: "same-origin" });
  if (response.status === 401 && !String(url).includes("/api/auth/")) showAuthGate(false);
  return response;
}

const moduleInfo = {
  regras: ["✓", "Regras e procedimentos", "Consulte o conhecimento já indexado em AVOPs, manuais, programas de instrução e regras aprovadas."],
  instrutores: ["♙", "Instrutores", "Este módulo reunirá habilitações, qualificações, disponibilidade e restrições individuais dos instrutores."],
  aeronaves: ["✈", "Aeronaves e manutenção", "Este módulo exibirá situação da frota, horas, vencimentos, limitações e indisponibilidades de manutenção."],
  manutencao: ["◇", "Manutenção", "Acompanhamento de inspeções, vencimentos, discrepâncias e retorno ao serviço será integrado aqui."],
  restricoes: ["!", "Restrições operacionais", "Centralização de restrições temporárias por aeródromo, base, aeronave, instrutor e aluno."],
  consulta: ["⌕", "Consultar base", "Use a pesquisa da visão geral para consultar as primeiras regras já validadas."],
};

const $ = (selector) => document.querySelector(selector);
const homeView = $("#homeView");
const answerView = $("#answerView");
const moduleView = $("#moduleView");
const instructorsView = $("#instructorsView");
const aircraftView = $("#aircraftView");
const handoverView = $("#handoverView");
const usersView = $("#usersView");
const input = $("#searchInput");
const searchBox = $("#searchForm");
const searchResults = $("#searchResults");
const searchProgress = $("#searchProgress");
const progressSteps = [...document.querySelectorAll("[data-progress-step]")];
const progressStages = [
  ["Pergunta recebida", "Sua consulta foi recebida e será pesquisada na base SAFE.", 16],
  ["Consultando a base de conhecimento", "Localizando regras, documentos e relações relevantes.", 43],
  ["Analisando as evidências", "Conferindo fontes e conexões antes de elaborar a resposta.", 72],
  ["Preparando a resposta", "Organizando a orientação e as fontes para apresentação.", 92],
];
let suggestionItems = [];
let activeSuggestion = -1;
let history = [];
let archivedQuestion = "";
let searchInProgress = false;
let progressTimers = [];
let progressClock = null;
let instructors = [];
let instructorsLoaded = false;
let aircraft = [];
let aircraftLoaded = false;
let operationalBases = [];
let basesPromise = null;
let handovers = [];
let handoversLoaded = false;
let users = [];
let usersLoaded = false;
const instructorReleases = ["Liberado MC01", "Liberado C150", "Liberado P-Mentor VFR/IFR SIC", "Liberado IFR Avião", "Liberado IFR AATD", "Liberado IFR PCATD (Laboratório)", "Liberado COLT", "Instrutor Eventual"];

function loadOperationalBases() {
  if (basesPromise) return basesPromise;
  basesPromise = apiFetch(`${window.location.origin}/api/bases`)
    .then(async response => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Não foi possível carregar as bases.");
      operationalBases = data.items.filter(item => item.status === "Ativa");
      return operationalBases;
    })
    .catch(error => {
      basesPromise = null;
      throw error;
    });
  return basesPromise;
}

function renderBaseSelect(select, includeUnassigned, selected = "") {
  select.innerHTML = `${includeUnassigned ? '<option value="Não informada">Não informada</option>' : '<option value="">Selecione a base</option>'}${operationalBases.map(item => `<option value="${escapeHtml(item.code)}">${escapeHtml(item.code)} · ${escapeHtml(item.name)}</option>`).join("")}`;
  select.value = selected || (includeUnassigned ? "Não informada" : "");
}

function showView(view, name) {
  [homeView, answerView, moduleView, instructorsView, aircraftView, handoverView, usersView].forEach(item => item.classList.add("hidden"));
  view.classList.remove("hidden");
  $("#pageName").textContent = name;
  window.scrollTo({ top: 0, behavior: "smooth" });
  $("#sidebar").classList.remove("open");
}

function renderHistory() {
  const box = $("#recentList");
  if (!history.length) { box.innerHTML = `<div class="empty-recent">Suas consultas aparecerão aqui.</div>`; return; }
  box.innerHTML = history.slice(0, 5).map(item => `<button class="recent-item" data-search-record="${escapeHtml(item.id)}" style="width:100%;border-left:0;border-right:0;border-bottom:0;background:none;text-align:left;cursor:pointer"><span class="recent-type">⌕</span><span class="recent-text"><strong>${escapeHtml(item.question)}</strong><small>${formatInstructorDate(item.created_at)} · ${item.response_mode === "local" ? "Índice local" : "Resposta armazenada"}</small></span><span>→</span></button>`).join("");
  box.querySelectorAll("[data-search-record]").forEach(button => button.addEventListener("click", () => openStoredSearch(button.dataset.searchRecord)));
}

async function loadSearchHistory() {
  try {
    const response = await apiFetch(`${window.location.origin}/api/searches?limit=10`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Não foi possível carregar o histórico.");
    history = data.items;
    renderHistory();
  } catch (error) {
    console.info("Histórico persistente indisponível.", error.message);
    renderHistory();
  }
}

async function openStoredSearch(recordId) {
  try {
    const response = await apiFetch(`${window.location.origin}/api/searches/${encodeURIComponent(recordId)}`);
    const record = await response.json();
    if (!response.ok) throw new Error(record.error || "Pesquisa não encontrada.");
    let presentation;
    if (record.presentation) presentation = record.presentation;
    else if (record.result) presentation = apiResultAnswer(record.question, record.result);
    else throw new Error("O registro não contém uma resposta armazenada.");
    showAnswer(presentation, record.question, { archivedAt: record.created_at });
  } catch (error) {
    toast(error.message);
  }
}

function findAnswer(query) {
  const normalized = query.toLocaleLowerCase("pt-BR");
  let best = null, score = 0;
  knowledge.forEach(item => { const current = item.keys.filter(key => normalized.includes(key)).length; if (current > score) { score = current; best = item; } });
  return score ? best : null;
}

function normalizeText(value) {
  return (value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR");
}

function tokenize(value) {
  const ignored = new Set(["a", "as", "o", "os", "de", "da", "das", "do", "dos", "e", "em", "na", "no", "para", "por", "com", "um", "uma", "que"]);
  return normalizeText(value).split(/[^a-z0-9-]+/).filter(token => token.length > 1 && !ignored.has(token));
}

function scoreRecord(record, tokens) {
  const label = normalizeText(record.label);
  const source = normalizeText(`${record.code || ""} ${record.source || ""} ${record.appliesTo || ""}`);
  return tokens.reduce((total, token) => total + (label.includes(token) ? 4 : 0) + (source.includes(token) ? 1 : 0), 0);
}

function findGraphResults(query) {
  const tokens = tokenize(query);
  if (!tokens.length) return [];
  const medicalIntent = tokens.includes("cma") || normalizeText(query).includes("certificado medico");
  return [...graphIndex.claims.map(item => ({ ...item, kind: "Regra confirmada" })), ...graphIndex.documents.map(item => ({ ...item, kind: "Documento relacionado" }))]
    .filter(item => {
      if (!medicalIntent) return true;
      const medicalText = normalizeText(`${item.label || ""} ${item.code || ""} ${item.source || ""} ${item.appliesTo || ""}`);
      return medicalText.includes("cma") || medicalText.includes("certificado medico");
    })
    .map(item => {
      const medicalText = normalizeText(`${item.label || ""} ${item.appliesTo || ""}`);
      const intentBoost = medicalIntent && medicalText.includes("matricula") ? 8 : 0;
      return { ...item, score: scoreRecord(item, tokens) + intentBoost };
    })
    .filter(item => item.score >= (medicalIntent ? 4 : Math.max(4, tokens.length * 2)))
    .sort((a, b) => b.score - a.score || a.label.localeCompare(b.label, "pt-BR"))
    .slice(0, 5);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"]/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[character]);
}

function renderSearchSuggestions() {
  const query = input.value.trim();
  searchBox.classList.toggle("has-value", Boolean(query));
  if (query.length < 2) { closeSearchSuggestions(); return; }
  suggestionItems = findGraphResults(query).slice(0, 6);
  activeSuggestion = -1;
  if (!suggestionItems.length) { closeSearchSuggestions(); return; }
  searchResults.innerHTML = suggestionItems.map((item, index) => `<button class="search-result" type="button" role="option" data-result="${index}" aria-selected="false"><span class="search-result-icon">${item.kind === "Regra confirmada" ? "✓" : "▤"}</span><span class="search-result-text"><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.kind)}${item.code ? ` · ${escapeHtml(item.code)}` : ""}</small></span>${item.kind === "Regra confirmada" ? '<span class="search-result-score">CONFIRMADA</span>' : ""}</button>`).join("");
  searchResults.classList.remove("hidden");
  searchResults.querySelectorAll("[data-result]").forEach(button => button.addEventListener("mousedown", event => { event.preventDefault(); selectSuggestion(Number(button.dataset.result)); }));
}

function closeSearchSuggestions() {
  searchResults.classList.add("hidden");
  searchResults.innerHTML = "";
  suggestionItems = [];
  activeSuggestion = -1;
}

function clearProgressTimers() {
  progressTimers.forEach(timer => clearTimeout(timer));
  progressTimers = [];
  if (progressClock) clearInterval(progressClock);
  progressClock = null;
}

function setProgressStage(index) {
  const [title, detail, percentage] = progressStages[index];
  $("#progressTitle").textContent = title;
  $("#progressDetail").textContent = detail;
  $("#progressBar").style.width = `${percentage}%`;
  progressSteps.forEach((step, position) => {
    step.classList.toggle("done", position < index);
    step.classList.toggle("active", position === index);
  });
}

function startSearchProgress() {
  clearProgressTimers();
  searchProgress.dataset.state = "running";
  searchProgress.classList.remove("hidden");
  searchBox.setAttribute("aria-busy", "true");
  $("#progressElapsed").textContent = "0 s";
  setProgressStage(0);
  const startedAt = Date.now();
  progressClock = setInterval(() => {
    $("#progressElapsed").textContent = `${Math.floor((Date.now() - startedAt) / 1000)} s`;
  }, 1000);
  progressTimers.push(setTimeout(() => setProgressStage(1), 250));
  progressTimers.push(setTimeout(() => setProgressStage(2), 1200));
  progressTimers.push(setTimeout(() => setProgressStage(3), 3500));
}

function showLocalFallbackProgress() {
  clearProgressTimers();
  searchProgress.dataset.state = "fallback";
  $("#progressTitle").textContent = "Consultando o índice local";
  $("#progressDetail").textContent = "O serviço de análise não respondeu. Buscando regras confirmadas disponíveis neste dispositivo.";
  $("#progressBar").style.width = "82%";
  progressSteps.forEach((step, position) => {
    step.classList.toggle("done", position < 2);
    step.classList.toggle("active", position === 2);
  });
}

async function finishSearchProgress(usedLocalFallback = false) {
  clearProgressTimers();
  searchProgress.dataset.state = "done";
  $("#progressTitle").textContent = "Resposta pronta";
  $("#progressDetail").textContent = usedLocalFallback ? "Consulta concluída com o índice local disponível." : "Consulta concluída com análise da base de conhecimento.";
  $("#progressBar").style.width = "100%";
  progressSteps.forEach(step => { step.classList.add("done"); step.classList.remove("active"); });
  await new Promise(resolve => setTimeout(resolve, 450));
}

function stopSearchProgress() {
  clearProgressTimers();
  searchProgress.classList.add("hidden");
  searchProgress.removeAttribute("data-state");
  searchBox.setAttribute("aria-busy", "false");
}

function highlightSuggestion(index) {
  const buttons = [...searchResults.querySelectorAll("[data-result]")];
  if (!buttons.length) return;
  activeSuggestion = (index + buttons.length) % buttons.length;
  buttons.forEach((button, position) => {
    const active = position === activeSuggestion;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active);
  });
  buttons[activeSuggestion].scrollIntoView({ block: "nearest" });
}

function selectSuggestion(index) {
  const item = suggestionItems[index];
  if (!item) return;
  input.value = item.label;
  closeSearchSuggestions();
  search(item.label);
}

function graphResultAnswer(query, results) {
  const confirmed = results.filter(item => item.kind === "Regra confirmada");
  const primary = confirmed[0] || results[0];
  const related = results.slice(1).map(item => `<div class="answer-highlight"><strong>${escapeHtml(item.label)}</strong><br><small>${escapeHtml(item.kind)}${item.code ? ` · ${escapeHtml(item.code)}` : ""}${item.location ? ` · ${escapeHtml(item.location)}` : ""}</small></div>`).join("");
  return {
    question: query,
    answer: `<div class="answer-highlight"><strong>Modo de contingência: a Gemini não respondeu nesta consulta.</strong><br><small>Este é um resultado lexical do índice local. Confirme a conclusão na fonte oficial antes de decidir.</small></div><p>Regra confirmada localizada:</p><div class="answer-highlight"><strong>${escapeHtml(primary.label)}</strong><br><small>${primary.code ? escapeHtml(primary.code) : "Regra SAFE"}${primary.location ? ` · ${escapeHtml(primary.location)}` : ""}</small></div>${related ? `<p><strong>Regras relacionadas:</strong></p>${related}` : ""}`,
    source: primary.code || primary.label,
    detail: `Resultado local sem interpretação de contexto · ${primary.source || "Regra confirmada no grafo SAFE"}${primary.location ? ` · ${primary.location}` : ""}`,
    relations: results.slice(0, 3).map(item => [item.kind.toUpperCase(), item.label, item.code || item.source || "Grafo SAFE"])
  };
}

function apiResultAnswer(query, result) {
  const confidenceLabels = { high: "Alta confiança", medium: "Confiança moderada", low: "Baixa confiança" };
  const sources = result.sources || [];
  return {
    question: query,
    answer: `<p>${escapeHtml(result.answer).replace(/\n/g, "<br>")}</p><div class="answer-highlight"><strong>${confidenceLabels[result.confidence] || "Confiança não informada"}</strong><br><small>Consulta ${escapeHtml(result.query_id || "")} · ${result.candidate_relations_count || 0} nova(s) relação(ões) candidata(s)</small></div>`,
    source: sources[0]?.code || sources[0]?.label || "Grafo SAFE + Gemini",
    detail: sources[0] ? `${sources[0].location || "Localização não informada"}` : "Nenhuma evidência suficiente localizada",
    relations: sources.slice(0, 3).map(item => [item.kind === "confirmed_claim" ? "REGRA CONFIRMADA" : "DOCUMENTO", item.label, item.code || item.location || "Grafo SAFE"]),
  };
}

async function askApi(query) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 50000);
  try {
    const response = await apiFetch(API_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: query }), signal: controller.signal });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Erro HTTP ${response.status}`);
    return data;
  } finally { clearTimeout(timeout); }
}

async function saveLocalSearchRecord(question, presentation) {
  try {
    const response = await apiFetch(`${window.location.origin}/api/searches`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, confidence: "low", presentation }),
    });
    if (!response.ok) throw new Error("Histórico local não pôde ser salvo.");
  } catch (error) {
    console.info(error.message);
  }
}

function showAnswer(item, originalQuestion, options = {}) {
  $("#answerQuestion").textContent = originalQuestion || item.question;
  $("#answerBody").innerHTML = item.answer;
  $("#sourceTitle").textContent = item.source;
  $("#sourceDetail").textContent = item.detail;
  $("#relationList").innerHTML = item.relations.map(r => `<div class="relation"><small>${r[0]}</small><strong>${r[1]}</strong><span>${r[2]}</span></div>`).join("");
  const storedAnswer = Boolean(options.archivedAt || options.storedDetail);
  archivedQuestion = storedAnswer ? (originalQuestion || item.question) : "";
  $("#archivedAnswerNotice").classList.toggle("hidden", !storedAnswer);
  if (storedAnswer) {
    $("#archivedAnswerTitle").textContent = options.storedTitle || "Pesquisa armazenada";
    $("#archivedAnswerDate").textContent = options.storedDetail || `Resposta registrada em ${formatInstructorDate(options.archivedAt)}.`;
  }
  showView(answerView, "Resposta");
}

async function search(query) {
  if (!query.trim()) { input.focus(); return; }
  if (searchInProgress) return;
  searchInProgress = true;
  closeSearchSuggestions();
  const submitButton = searchBox.querySelector('button[type="submit"]');
  const originalLabel = submitButton.textContent;
  submitButton.disabled = true; submitButton.textContent = "Consultando…";
  input.readOnly = true;
  startSearchProgress();
  try {
    const apiResult = await askApi(query);
    await finishSearchProgress(false);
    showAnswer(apiResultAnswer(query, apiResult), query);
    loadSearchHistory();
  } catch (error) {
    console.info("Backend de IA indisponível; usando busca local.", error.message);
    showLocalFallbackProgress();
    await new Promise(resolve => setTimeout(resolve, 500));
    const answer = findAnswer(query);
    let localResult;
    if (answer) localResult = answer;
    else {
      const results = findGraphResults(query);
      if (results.length) localResult = graphResultAnswer(query, results);
      else localResult = { question: query, answer: `<p>Não encontrei uma regra confirmada para esta pergunta no índice atual.</p><div class="answer-highlight"><strong>Não tome uma decisão apenas com esta resposta.</strong> Consulte a documentação oficial ou encaminhe a dúvida para revisão.</div>`, source: "Nenhuma fonte confirmada localizada", detail: "Consulta pendente de ampliação da base", relations: [["STATUS", "Conhecimento ainda não indexado", "Requer análise documental"], ["PRÓXIMA AÇÃO", "Consultar documentação oficial", "Validação humana necessária"]] };
    }
    await finishSearchProgress(true);
    await saveLocalSearchRecord(query, localResult);
    showAnswer(localResult, query);
    loadSearchHistory();
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = originalLabel;
    input.readOnly = false;
    searchInProgress = false;
    stopSearchProgress();
  }
}

function releaseKind(value) {
  const normalized = normalizeText(value);
  if (normalized.includes("mc01")) return "mc01";
  if (normalized.includes("c150")) return "c150";
  if (normalized.includes("mentor")) return "mentor";
  if (normalized.includes("ifr")) return "ifr";
  if (normalized.includes("colt")) return "colt";
  if (normalized.includes("eventual")) return "eventual";
  return "other";
}

function formatInstructorDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function fillInstructorFilters() {
  const base = $("#baseFilter").value;
  const group = $("#groupFilter").value;
  const bases = [...new Set(instructors.map(item => item.base))].sort();
  const groups = [...new Set(instructors.map(item => item.group))].sort();
  $("#baseFilter").innerHTML = `<option value="">Todas as bases</option>${bases.map(value => `<option>${escapeHtml(value)}</option>`).join("")}`;
  $("#groupFilter").innerHTML = `<option value="">Todos os grupos</option>${groups.map(value => `<option>${escapeHtml(value)}</option>`).join("")}`;
  $("#baseFilter").value = bases.includes(base) ? base : "";
  $("#groupFilter").value = groups.includes(group) ? group : "";
}

function renderInstructorSnapshot() {
  const box = $("#instructorSnapshot");
  if (!box) return;
  const countBy = key => [...new Set(instructors.map(item => item[key]))].sort().map(value => [value, instructors.filter(item => item[key] === value).length]);
  const bases = countBy("base");
  const groups = countBy("group");
  box.innerHTML = `<div class="instructor-snapshot-grid">
    <div class="snapshot-total"><small>Total da equipe</small><strong>${instructors.length}</strong></div>
    <div class="snapshot-group"><small>Por base</small>${bases.map(([value, count]) => `<div><span>${escapeHtml(value)}</span><b>${count}</b></div>`).join("")}</div>
    <div class="snapshot-group"><small>Por grupo</small>${groups.map(([value, count]) => `<div><span>${escapeHtml(value)}</span><b>${count}</b></div>`).join("")}</div>
  </div>`;
}

function renderInstructors() {
  const query = normalizeText($("#instructorSearch").value);
  const base = $("#baseFilter").value;
  const group = $("#groupFilter").value;
  const visible = instructors.filter(item => {
    const searchable = normalizeText(`${item.name} ${item.base} ${item.group} ${item.releases.join(" ")}`);
    return (!query || searchable.includes(query)) && (!base || item.base === base) && (!group || item.group === group);
  });
  $("#instructorTotal").textContent = `${visible.length} de ${instructors.length} instrutor${instructors.length === 1 ? "" : "es"}`;
  $("#instructorRows").innerHTML = visible.length ? visible.map(item => `
    <tr>
      <td><span class="instructor-name">${escapeHtml(item.name)}</span></td>
      <td><span class="base-badge ${item.base === "CPQ" ? "cpq" : ""}">${escapeHtml(item.base)}</span></td>
      <td><span class="group-badge ${normalizeText(item.group).includes("solo") ? "solo" : ""}">${escapeHtml(item.group)}</span></td>
      <td><div class="release-list">${item.releases.length ? item.releases.map(value => `<span class="release-chip" data-kind="${releaseKind(value)}">${escapeHtml(value)}</span>`).join("") : "<span>—</span>"}</div></td>
      <td class="updated-cell">${formatInstructorDate(item.updated_at)}</td>
      <td class="row-actions">${hasRole("admin", "supervisor") ? `<button class="edit-instructor" data-instructor-id="${item.id}" aria-label="Editar ${escapeHtml(item.name)}">✎</button>` : ""}</td>
    </tr>`).join("") : `<tr><td colspan="6" class="table-message">Nenhum instrutor encontrado com esses filtros.</td></tr>`;
  document.querySelectorAll("[data-instructor-id]").forEach(button => button.addEventListener("click", () => openInstructorDialog(instructors.find(item => item.id === Number(button.dataset.instructorId)))));
  renderInstructorSnapshot();
}

async function instructorRequest(path = "", options = {}) {
  const response = await apiFetch(`${window.location.origin}/api/instructors${path}`, {
    ...options,
    headers: options.body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Erro HTTP ${response.status}`);
  return data;
}

async function loadInstructors() {
  $("#instructorRows").innerHTML = `<tr><td colspan="6" class="table-message">Carregando banco de instrutores…</td></tr>`;
  try {
    const data = await instructorRequest();
    instructors = data.items;
    instructorsLoaded = true;
    fillInstructorFilters();
    renderInstructors();
  } catch (error) {
    $("#instructorRows").innerHTML = `<tr><td colspan="6" class="table-message">Não foi possível acessar o banco. Inicie o portal pelo servidor local.</td></tr>`;
    toast(error.message);
  }
}

async function openInstructorDialog(item = null) {
  try { await loadOperationalBases(); } catch (error) { toast(error.message); return; }
  $("#instructorForm").reset();
  $("#instructorId").value = item?.id || "";
  $("#instructorName").value = item?.name || "";
  renderBaseSelect($("#instructorBase"), false, item?.base || "");
  $("#instructorGroup").value = item?.group || "";
  $("#instructorDialogTitle").textContent = item ? "Editar instrutor" : "Novo instrutor";
  $("#deleteInstructor").classList.toggle("hidden", !item);
  $("#releaseOptions").innerHTML = instructorReleases.map(value => `<label class="release-option"><input type="checkbox" name="release" value="${escapeHtml(value)}" ${item?.releases.includes(value) ? "checked" : ""}>${escapeHtml(value)}</label>`).join("");
  $("#instructorDialog").showModal();
  setTimeout(() => $("#instructorName").focus(), 50);
}

async function saveInstructor(event) {
  event.preventDefault();
  const id = $("#instructorId").value;
  const payload = {
    name: $("#instructorName").value,
    base: $("#instructorBase").value,
    group: $("#instructorGroup").value,
    releases: [...document.querySelectorAll('input[name="release"]:checked')].map(input => input.value),
  };
  const button = $("#saveInstructor");
  button.disabled = true;
  try {
    const saved = await instructorRequest(id ? `/${id}` : "", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) });
    const index = instructors.findIndex(item => item.id === saved.id);
    if (index >= 0) instructors[index] = saved; else instructors.push(saved);
    fillInstructorFilters();
    renderInstructors();
    $("#instructorDialog").close();
    toast(id ? "Instrutor atualizado com sucesso." : "Instrutor cadastrado com sucesso.");
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
}

async function removeInstructor() {
  const id = Number($("#instructorId").value);
  const item = instructors.find(value => value.id === id);
  if (!item || !window.confirm(`Excluir ${item.name} do banco de instrutores?`)) return;
  const button = $("#deleteInstructor");
  button.disabled = true;
  try {
    await instructorRequest(`/${id}`, { method: "DELETE" });
    instructors = instructors.filter(value => value.id !== id);
    fillInstructorFilters();
    renderInstructors();
    $("#instructorDialog").close();
    toast("Instrutor excluído.");
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
}

function aircraftStatusClass(status) {
  const value = normalizeText(status);
  if (value.includes("manuten")) return "maintenance";
  if (value.includes("fora") || value.includes("inativ")) return "inactive";
  return "";
}

function fillAircraftFilters() {
  const selectedBase = $("#aircraftBaseFilter").value;
  const selectedStatus = $("#aircraftStatusFilter").value;
  const bases = [...new Set(aircraft.map(item => item.base))].sort();
  const statuses = [...new Set(aircraft.map(item => item.status))].sort();
  $("#aircraftBaseFilter").innerHTML = `<option value="">Todas as bases</option>${bases.map(value => `<option>${escapeHtml(value)}</option>`).join("")}`;
  $("#aircraftStatusFilter").innerHTML = `<option value="">Todos os status</option>${statuses.map(value => `<option>${escapeHtml(value)}</option>`).join("")}`;
  $("#aircraftBaseFilter").value = bases.includes(selectedBase) ? selectedBase : "";
  $("#aircraftStatusFilter").value = statuses.includes(selectedStatus) ? selectedStatus : "";
}

function renderRestrictedAircraftDashboard() {
  const box = $("#restrictedAircraftList");
  if (!box) return;
  const restricted = aircraft.filter(item => item.status !== "Operacional");
  if (!restricted.length) {
    box.innerHTML = `<div class="dashboard-clear"><span>✓</span>Nenhuma aeronave possui restrição registrada.</div>`;
    return;
  }
  box.innerHTML = restricted.map(item => {
    const restriction = item.status === "Em Manutenção"
      ? "Aeronave indisponível por manutenção"
      : "Aeronave fora de operação";
    return `<div class="restriction-dashboard-item"><span class="restriction-aircraft-icon">✈</span><div><strong>${escapeHtml(item.registration)} · ${escapeHtml(item.model)}</strong><small>${escapeHtml(restriction)}</small></div><span class="status-badge ${aircraftStatusClass(item.status)}">${escapeHtml(item.status)}</span></div>`;
  }).join("");
}

function renderAircraft() {
  const query = normalizeText($("#aircraftSearch").value);
  const base = $("#aircraftBaseFilter").value;
  const status = $("#aircraftStatusFilter").value;
  const visible = aircraft.filter(item => {
    const searchable = normalizeText(`${item.model} ${item.registration} ${item.base} ${item.status} ${item.operation_type} ${item.active_restrictions} ${item.temporary_restrictions}`);
    return (!query || searchable.includes(query)) && (!base || item.base === base) && (!status || item.status === status);
  });
  $("#aircraftTotal").textContent = `${visible.length} de ${aircraft.length} aeronave${aircraft.length === 1 ? "" : "s"}`;
  $("#aircraftRows").innerHTML = visible.length ? visible.map(item => `
    <tr>
      <td><span class="instructor-name">${escapeHtml(item.model)}</span></td>
      <td><span class="registration">${escapeHtml(item.registration)}</span></td>
      <td><span class="base-badge ${item.base === "CPQ" ? "cpq" : ""}">${escapeHtml(item.base)}</span></td>
      <td><span class="status-badge ${aircraftStatusClass(item.status)}">${escapeHtml(item.status)}</span></td>
      <td>${escapeHtml(item.operation_type)}</td>
      <td class="restriction-cell">
        <strong>${escapeHtml(item.active_restrictions)}</strong>
        <div class="temporary-restriction ${normalizeText(item.temporary_restrictions) === "nenhuma" ? "is-clear" : "has-restriction"}">
          <span>${normalizeText(item.temporary_restrictions) === "nenhuma" ? "✓" : "!"}</span>
          <div><b>${normalizeText(item.temporary_restrictions) === "nenhuma" ? "OK · sem restrição temporária" : "Tem restrição temporária"}</b>${normalizeText(item.temporary_restrictions) !== "nenhuma" ? `<small>${escapeHtml(item.temporary_restrictions)}${item.restriction_date ? ` · ${escapeHtml(item.restriction_date.split("-").reverse().join("/"))}` : ""}</small>` : ""}</div>
        </div>
      </td>
      <td class="updated-cell">${formatInstructorDate(item.updated_at)}</td>
      <td class="row-actions">${hasRole("admin", "supervisor") ? `<button class="edit-instructor" data-aircraft-id="${item.id}" aria-label="Editar ${escapeHtml(item.registration)}">✎</button>` : ""}</td>
    </tr>`).join("") : `<tr><td colspan="8" class="table-message">Nenhuma aeronave encontrada com esses filtros.</td></tr>`;
  document.querySelectorAll("[data-aircraft-id]").forEach(button => button.addEventListener("click", () => openAircraftDialog(aircraft.find(item => item.id === Number(button.dataset.aircraftId)))));
  renderRestrictedAircraftDashboard();
}

async function aircraftRequest(path = "", options = {}) {
  const response = await apiFetch(`${window.location.origin}/api/aircraft${path}`, {
    ...options,
    headers: options.body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Erro HTTP ${response.status}`);
  return data;
}

async function loadAircraft() {
  $("#aircraftRows").innerHTML = `<tr><td colspan="8" class="table-message">Carregando banco de aeronaves…</td></tr>`;
  try {
    const data = await aircraftRequest();
    aircraft = data.items;
    aircraftLoaded = true;
    fillAircraftFilters();
    renderAircraft();
  } catch (error) {
    $("#aircraftRows").innerHTML = `<tr><td colspan="8" class="table-message">Não foi possível acessar o banco de aeronaves.</td></tr>`;
    toast(error.message);
  }
}

async function openAircraftDialog(item = null) {
  try { await loadOperationalBases(); } catch (error) { toast(error.message); return; }
  $("#aircraftForm").reset();
  $("#aircraftId").value = item?.id || "";
  $("#aircraftModel").value = item?.model || "";
  $("#aircraftRegistration").value = item?.registration || "";
  renderBaseSelect($("#aircraftBase"), true, item?.base || "Não informada");
  $("#aircraftStatus").value = item?.status || "Operacional";
  $("#aircraftOperation").value = item?.operation_type || "";
  $("#aircraftActiveRestrictions").value = item?.active_restrictions || "Nenhuma";
  $("#aircraftTemporaryRestrictions").value = item?.temporary_restrictions || "Nenhuma";
  $("#aircraftRestrictionDate").value = item?.restriction_date || "";
  $("#aircraftDialogTitle").textContent = item ? "Editar aeronave" : "Nova aeronave";
  $("#deleteAircraft").classList.toggle("hidden", !item);
  $("#aircraftDialog").showModal();
  setTimeout(() => $("#aircraftModel").focus(), 50);
}

async function saveAircraft(event) {
  event.preventDefault();
  const id = $("#aircraftId").value;
  const payload = {
    model: $("#aircraftModel").value, registration: $("#aircraftRegistration").value,
    base: $("#aircraftBase").value, status: $("#aircraftStatus").value,
    operation_type: $("#aircraftOperation").value,
    active_restrictions: $("#aircraftActiveRestrictions").value,
    temporary_restrictions: $("#aircraftTemporaryRestrictions").value,
    restriction_date: $("#aircraftRestrictionDate").value,
  };
  const button = $("#saveAircraft");
  button.disabled = true;
  try {
    const saved = await aircraftRequest(id ? `/${id}` : "", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) });
    const index = aircraft.findIndex(item => item.id === saved.id);
    if (index >= 0) aircraft[index] = saved; else aircraft.push(saved);
    fillAircraftFilters(); renderAircraft(); $("#aircraftDialog").close();
    toast(id ? "Aeronave atualizada com sucesso." : "Aeronave cadastrada com sucesso.");
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; }
}

async function removeAircraft() {
  const id = Number($("#aircraftId").value);
  const item = aircraft.find(value => value.id === id);
  if (!item || !window.confirm(`Excluir a aeronave ${item.registration}?`)) return;
  const button = $("#deleteAircraft");
  button.disabled = true;
  try {
    await aircraftRequest(`/${id}`, { method: "DELETE" });
    aircraft = aircraft.filter(value => value.id !== id);
    fillAircraftFilters(); renderAircraft(); $("#aircraftDialog").close(); toast("Aeronave excluída.");
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; }
}

async function handoverRequest(path = "", options = {}) {
  const response = await apiFetch(`${window.location.origin}/api/handovers${path}`, {
    ...options,
    headers: options.body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Erro HTTP ${response.status}`);
  return data;
}

function handoverCard(item) {
  const canEdit = hasRole("admin", "supervisor", "operator");
  const nextStatus = item.status === "Pendente" ? "Em andamento" : item.status === "Em andamento" ? "Concluída" : "";
  const nextLabel = item.status === "Pendente" ? "Assumir" : item.status === "Em andamento" ? "Concluir" : "";
  return `<article class="handover-card priority-${normalizeText(item.priority)}">
    <div class="handover-card-top"><span class="shift-route">${item.origin_shift} → ${item.target_shift}</span><span class="priority-label">${escapeHtml(item.priority)}</span><span class="handover-card-time">${formatInstructorDate(item.updated_at)}</span></div>
    <p>${escapeHtml(item.message)}</p>
    <span class="handover-author">Deixado por <strong>${escapeHtml(item.author)}</strong></span>
    ${canEdit ? `<div class="handover-card-actions">${nextStatus ? `<button class="advance" data-handover-status="${item.id}" data-next-status="${nextStatus}">${nextLabel}</button>` : ""}<button data-handover-edit="${item.id}">Editar</button></div>` : ""}
  </article>`;
}

function renderHandovers() {
  const target = $("#handoverShiftFilter").value;
  const visible = handovers.filter(item => !target || item.target_shift === target);
  const counts = status => handovers.filter(item => item.status === status).length;
  $("#handoverPendingCount").textContent = counts("Pendente");
  $("#handoverProgressCount").textContent = counts("Em andamento");
  $("#handoverDoneCount").textContent = counts("Concluída");
  const openCount = counts("Pendente") + counts("Em andamento");
  $("#handoverNavCount").textContent = openCount;
  $("#notificationCount").textContent = openCount > 99 ? "99+" : openCount;
  $("#notificationCount").classList.toggle("hidden", openCount === 0);
  const columns = ["Pendente", "Em andamento", "Concluída"];
  $("#handoverBoard").innerHTML = columns.map(status => {
    const items = visible.filter(item => item.status === status);
    return `<section class="handover-column"><div class="handover-column-head"><strong>${status}</strong><span>${items.length}</span></div>${items.length ? items.map(handoverCard).join("") : '<div class="handover-empty">Nenhuma passagem nesta etapa.</div>'}</section>`;
  }).join("");
  document.querySelectorAll("[data-handover-edit]").forEach(button => button.addEventListener("click", () => openHandoverDialog(handovers.find(item => item.id === Number(button.dataset.handoverEdit)))));
  document.querySelectorAll("[data-handover-status]").forEach(button => button.addEventListener("click", () => updateHandoverStatus(Number(button.dataset.handoverStatus), button.dataset.nextStatus)));
}

async function loadHandovers() {
  try {
    const data = await handoverRequest();
    handovers = data.items;
    handoversLoaded = true;
    renderHandovers();
  } catch (error) {
    $("#handoverBoard").innerHTML = `<div class="table-message">Não foi possível carregar as passagens de turno.</div>`;
    toast(error.message);
  }
}

function openHandoverDialog(item = null) {
  $("#handoverForm").reset();
  $("#handoverId").value = item?.id || "";
  $("#handoverOrigin").value = item?.origin_shift || "T1";
  $("#handoverTarget").value = item?.target_shift || "T2";
  $("#handoverPriority").value = item?.priority || "Normal";
  $("#handoverStatus").value = item?.status || "Pendente";
  $("#handoverAuthor").value = item?.author || localStorage.getItem("safe-cco-operator") || "";
  $("#handoverMessage").value = item?.message || "";
  $("#handoverDialogTitle").textContent = item ? "Editar passagem de turno" : "Nova passagem de turno";
  $("#deleteHandover").classList.toggle("hidden", !item);
  $("#handoverDialog").showModal();
  setTimeout(() => (item ? $("#handoverMessage") : $("#handoverAuthor")).focus(), 50);
}

function handoverPayload() {
  return {
    origin_shift: $("#handoverOrigin").value, target_shift: $("#handoverTarget").value,
    priority: $("#handoverPriority").value, status: $("#handoverStatus").value,
    author: $("#handoverAuthor").value, message: $("#handoverMessage").value,
  };
}

async function saveHandover(event) {
  event.preventDefault();
  const id = $("#handoverId").value;
  const payload = handoverPayload();
  const button = $("#saveHandover");
  button.disabled = true;
  try {
    const saved = await handoverRequest(id ? `/${id}` : "", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) });
    localStorage.setItem("safe-cco-operator", saved.author);
    const index = handovers.findIndex(item => item.id === saved.id);
    if (index >= 0) handovers[index] = saved; else handovers.unshift(saved);
    renderHandovers(); $("#handoverDialog").close(); toast(id ? "Passagem atualizada." : "Passagem registrada para o próximo turno.");
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; }
}

async function updateHandoverStatus(id, status) {
  const item = handovers.find(value => value.id === id);
  if (!item) return;
  try {
    const saved = await handoverRequest(`/${id}`, { method: "PUT", body: JSON.stringify({ ...item, status }) });
    handovers[handovers.findIndex(value => value.id === id)] = saved;
    renderHandovers();
    toast(status === "Concluída" ? "Pendência concluída." : "Pendência assumida pelo turno.");
  } catch (error) { toast(error.message); }
}

async function removeHandover() {
  const id = Number($("#handoverId").value);
  if (!id || !window.confirm("Excluir esta passagem de turno?")) return;
  const button = $("#deleteHandover");
  button.disabled = true;
  try {
    await handoverRequest(`/${id}`, { method: "DELETE" });
    handovers = handovers.filter(item => item.id !== id);
    renderHandovers(); $("#handoverDialog").close(); toast("Passagem excluída.");
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; }
}

function currentShiftStage(date = new Date()) {
  const minutes = date.getHours() * 60 + date.getMinutes();
  if (minutes < 480) return { icon: "—", phase: "closed", title: "Fora do horário", detail: "Próximo turno: T1 às 08:00" };
  if (minutes < 510) return { icon: "T1", phase: "start", title: "Início do turno T1", detail: "Abertura e leitura das pendências" };
  if (minutes < 705) return { icon: "T1", phase: "active", title: "Turno T1 em andamento", detail: "08:00–14:00" };
  if (minutes < 720) return { icon: "T1", phase: "end", title: "Preparar passagem", detail: "T1 encerra às 14:00" };
  if (minutes < 840) return { icon: "⇄", phase: "handover", title: "Cross-check de pendências", detail: "T1 ↔ T2 · passagem 12:00–14:00" };
  if (minutes < 1050) return { icon: "T2", phase: "active", title: "Turno T2 em andamento", detail: "12:00–18:00" };
  if (minutes < 1080) return { icon: "⇄", phase: "handover", title: "Fim do T2 · passagem", detail: "Revisar pendências para o T3" };
  if (minutes < 1110) return { icon: "T3", phase: "start", title: "Início do turno T3", detail: "Recebimento das pendências do T2" };
  if (minutes < 1170) return { icon: "T3", phase: "active", title: "Turno T3 em andamento", detail: "18:00–20:00" };
  if (minutes < 1200) return { icon: "T3", phase: "end", title: "Fim do turno T3", detail: "Encerrar ou registrar pendências" };
  return { icon: "—", phase: "closed", title: "Operação encerrada", detail: "Próximo turno: T1 às 08:00" };
}

function updateShiftStatus() {
  const now = new Date();
  const stage = currentShiftStage(now);
  $("#shiftStatusCard").dataset.phase = stage.phase;
  $("#shiftStatusIcon").textContent = stage.icon;
  $("#shiftStatusTitle").textContent = stage.title;
  $("#shiftStatusDetail").textContent = stage.detail;
  $("#shiftStatusTime").textContent = `Agora, ${new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" }).format(now)}`;
}

async function updateSystemStatus() {
  const status = $("#systemStatus");
  try {
    const response = await apiFetch(`${window.location.origin}/api/health`, { cache: "no-store" });
    if (!response.ok) throw new Error();
    status.dataset.state = "online";
    $("#systemStatusText").textContent = "Operacional";
  } catch {
    status.dataset.state = "offline";
    $("#systemStatusText").textContent = "Indisponível";
  }
}

function showAuthGate(setupRequired, setupTokenRequired = false) {
  $("#authGate").classList.remove("hidden");
  $("#authForm").dataset.mode = setupRequired ? "setup" : "login";
  $("#setupNameField").classList.toggle("hidden", !setupRequired);
  $("#setupTokenField").classList.toggle("hidden", !setupRequired || !setupTokenRequired);
  $("#authEyebrow").textContent = setupRequired ? "CONFIGURAÇÃO INICIAL" : "ACESSO RESTRITO";
  $("#authTitle").textContent = setupRequired ? "Criar Administrador" : "Entrar no PortalCCO";
  $("#authDescription").textContent = setupRequired
    ? (setupTokenRequired
      ? "Informe o código secreto definido na implantação e crie a primeira conta administrativa."
      : "Configure a primeira conta responsável pelo controle de acesso.")
    : "Use suas credenciais para acessar a operação.";
  $("#authSubmit").textContent = setupRequired ? "Criar e entrar" : "Entrar";
  $("#authDisplayName").required = setupRequired;
  $("#authSetupToken").required = setupRequired && setupTokenRequired;
  $("#authError").classList.add("hidden");
}

function applyCurrentUser(user, csrf) {
  currentUser = user;
  csrfToken = csrf;
  $("#authGate").classList.add("hidden");
  $("#operatorName").textContent = user.display_name;
  $("#operatorRole").textContent = user.role_label;
  $("#operatorAvatar").textContent = user.display_name.split(/\s+/).slice(0, 2).map(value => value[0]).join("").toUpperCase();
  $("#usersNavItem").classList.toggle("hidden", user.role !== "admin");
  $("#addInstructor").classList.toggle("hidden", !hasRole("admin", "supervisor"));
  $("#addAircraft").classList.toggle("hidden", !hasRole("admin", "supervisor"));
  $("#addHandover").classList.toggle("hidden", user.role === "viewer");
  $("#accountDialogName").textContent = user.display_name;
  $("#accountDialogRole").textContent = `${user.role_label} · ${user.username}`;
  if (user.must_change_password) {
    $("#accountDialog").showModal();
    toast("Altere sua senha temporária antes de continuar.");
  } else bootstrapPortal();
}

async function loginWithCredentials(username, password) {
  const response = await nativeFetch(`${window.location.origin}/api/auth/login`, {
    method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Não foi possível entrar.");
  applyCurrentUser(data.user, data.csrf_token);
}

async function initializeAuth() {
  try {
    const statusResponse = await nativeFetch(`${window.location.origin}/api/auth/status`, { cache: "no-store" });
    const status = await statusResponse.json();
    if (status.setup_required) {
      showAuthGate(true, status.setup_token_required);
      if (!status.setup_configured) {
        $("#authError").textContent = "O servidor ainda não possui o código secreto de implantação.";
        $("#authError").classList.remove("hidden");
      }
      return;
    }
    const meResponse = await nativeFetch(`${window.location.origin}/api/auth/me`, { credentials: "same-origin", cache: "no-store" });
    if (!meResponse.ok) { showAuthGate(false); return; }
    const me = await meResponse.json();
    applyCurrentUser(me.user, me.csrf_token);
  } catch {
    showAuthGate(false);
    $("#authError").textContent = "Servidor indisponível. Inicie o PortalCCO e tente novamente.";
    $("#authError").classList.remove("hidden");
  }
}

function bootstrapPortal() {
  if (portalBootstrapped) {
    renderInstructors(); renderAircraft(); renderHandovers();
    return;
  }
  portalBootstrapped = true;
  loadSearchHistory();
  loadHandovers();
  loadInstructors();
  loadAircraft();
  updateShiftStatus();
  updateSystemStatus();
  setInterval(updateShiftStatus, 30_000);
  setInterval(updateSystemStatus, 60_000);
  applyInitialRoute();
}

function applyInitialRoute() {
  const params = new URLSearchParams(window.location.search);
  const initialQuestion = params.get("q");
  const initialView = params.get("view");
  if (initialQuestion) { input.value = initialQuestion; searchBox.classList.add("has-value"); search(initialQuestion); }
  if (["instrutores", "aeronaves", "passagem", "usuarios"].includes(initialView)) {
    document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === initialView));
    openModule(initialView);
  }
}

async function loadUsers() {
  try {
    const response = await apiFetch(`${window.location.origin}/api/users`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Não foi possível carregar usuários.");
    users = data.items; usersLoaded = true; renderUsers();
  } catch (error) {
    $("#userRows").innerHTML = `<tr><td colspan="5" class="table-message">${escapeHtml(error.message)}</td></tr>`;
  }
}

function renderUsers() {
  $("#userRows").innerHTML = users.map(user => `<tr>
    <td><span class="instructor-name">${escapeHtml(user.display_name)}</span></td>
    <td>${escapeHtml(user.username)}</td>
    <td><span class="user-role-badge">${escapeHtml(user.role_label)}</span></td>
    <td><span class="user-state ${user.active ? "" : "inactive"}">${user.active ? "Ativo" : "Inativo"}</span></td>
    <td class="row-actions"><button class="edit-instructor" data-user-id="${user.id}" aria-label="Editar ${escapeHtml(user.display_name)}">✎</button></td>
  </tr>`).join("");
  document.querySelectorAll("[data-user-id]").forEach(button => button.addEventListener("click", () => requestUserEdit(users.find(user => user.id === Number(button.dataset.userId)))));
}

async function requestUserEdit(user) {
  if (!user) return;
  if (user.role !== "admin") { openUserDialog(user); return; }
  const password = window.prompt(`Digite a senha de ${user.display_name} para abrir os dados desta conta:`);
  if (!password) return;
  try {
    const response = await apiFetch(`${window.location.origin}/api/users/${user.id}/authorize-edit`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Não foi possível autorizar a edição.");
    openUserDialog(user, data.edit_token);
  } catch (error) { toast(error.message); }
}

function openUserDialog(user = null, editToken = "") {
  $("#userForm").reset();
  $("#userFormError").classList.add("hidden");
  $("#userId").value = user?.id || "";
  $("#userEditToken").value = editToken;
  $("#userDisplayName").value = user?.display_name || "";
  $("#userUsername").value = user?.username || "";
  $("#userRole").value = user?.role || "operator";
  $("#userActive").checked = user?.active ?? true;
  $("#userDialogTitle").textContent = user ? "Editar usuário" : "Novo usuário";
  $("#usernameField").classList.toggle("hidden", Boolean(user));
  $("#newUserPasswordField").classList.toggle("hidden", Boolean(user));
  $("#userActiveField").classList.toggle("hidden", !user);
  $("#resetUserPassword").classList.toggle("hidden", !user);
  $("#userUsername").required = !user;
  $("#userPassword").required = !user;
  $("#userDialog").showModal();
}

async function saveUser(event) {
  event.preventDefault();
  const errorBox = $("#userFormError");
  errorBox.classList.add("hidden");
  const id = $("#userId").value;
  const payload = id ? {
    display_name: $("#userDisplayName").value, role: $("#userRole").value, active: $("#userActive").checked,
    admin_edit_token: $("#userEditToken").value,
  } : {
    display_name: $("#userDisplayName").value, username: $("#userUsername").value,
    role: $("#userRole").value, password: $("#userPassword").value,
  };
  try {
    const response = await apiFetch(`${window.location.origin}/api/users${id ? `/${id}` : ""}`, {
      method: id ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Não foi possível salvar o usuário.");
    $("#userDialog").close(); await loadUsers(); toast(id ? "Usuário atualizado." : "Usuário criado com senha temporária.");
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("hidden");
  }
}

function openModule(key) {
  if (key === "inicio") { showView(homeView, "Regras e procedimentos"); return; }
  if (key === "regras" || key === "consulta") { showView(homeView, "Regras e procedimentos"); setTimeout(() => input.focus(), 200); return; }
  if (key === "instrutores") {
    showView(instructorsView, "Instrutores");
    if (!instructorsLoaded) loadInstructors();
    return;
  }
  if (key === "aeronaves") {
    showView(aircraftView, "Aeronaves");
    if (!aircraftLoaded) loadAircraft();
    return;
  }
  if (key === "passagem") {
    showView(handoverView, "Passagem de turno");
    if (!handoversLoaded) loadHandovers();
    return;
  }
  if (key === "usuarios") {
    if (!hasRole("admin")) { toast("Apenas administradores podem gerenciar usuários."); return; }
    showView(usersView, "Usuários e permissões");
    if (!usersLoaded) loadUsers();
    return;
  }
  const info = moduleInfo[key] || moduleInfo.restricoes;
  $("#moduleIcon").textContent = info[0]; $("#moduleTitle").textContent = info[1]; $("#moduleDescription").textContent = info[2];
  showView(moduleView, info[1]);
}

searchBox.addEventListener("submit", event => {
  event.preventDefault();
  if (activeSuggestion >= 0) selectSuggestion(activeSuggestion);
  else search(input.value);
});
input.addEventListener("input", renderSearchSuggestions);
input.addEventListener("keydown", event => {
  if (searchResults.classList.contains("hidden")) return;
  if (event.key === "ArrowDown") { event.preventDefault(); highlightSuggestion(activeSuggestion + 1); }
  if (event.key === "ArrowUp") { event.preventDefault(); highlightSuggestion(activeSuggestion - 1); }
  if (event.key === "Escape") { event.preventDefault(); closeSearchSuggestions(); }
});
input.addEventListener("blur", () => setTimeout(closeSearchSuggestions, 120));
$("#clearSearch").addEventListener("click", () => { input.value = ""; searchBox.classList.remove("has-value"); closeSearchSuggestions(); input.focus(); });
document.querySelectorAll("[data-faq]").forEach(button => button.addEventListener("click", () => {
  const stored = knowledge[Number(button.dataset.faq)];
  if (!stored) { toast("Resposta frequente não encontrada."); return; }
  showAnswer(stored, stored.question, {
    storedTitle: "Pergunta frequente armazenada",
    storedDetail: "Resposta previamente preparada e aberta sem executar uma nova consulta.",
  });
}));
document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => { document.querySelectorAll(".nav-item").forEach(item => item.classList.remove("active")); button.classList.add("active"); openModule(button.dataset.view); }));
document.querySelectorAll(".module-card").forEach(card => card.addEventListener("click", () => openModule(card.dataset.target)));
$("#backButton").addEventListener("click", () => showView(homeView, "Regras e procedimentos"));
$("#moduleBack").addEventListener("click", () => showView(homeView, "Regras e procedimentos"));
$("#returnHome").addEventListener("click", () => showView(homeView, "Regras e procedimentos"));
$("#menuButton").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
$("#sourceButton").addEventListener("click", () => toast("A abertura do documento original será conectada na próxima integração."));
$("#addInstructor").addEventListener("click", () => openInstructorDialog());
$("#instructorSearch").addEventListener("input", renderInstructors);
$("#baseFilter").addEventListener("change", renderInstructors);
$("#groupFilter").addEventListener("change", renderInstructors);
$("#instructorForm").addEventListener("submit", saveInstructor);
$("#deleteInstructor").addEventListener("click", removeInstructor);
$("#addAircraft").addEventListener("click", () => openAircraftDialog());
$("#aircraftSearch").addEventListener("input", renderAircraft);
$("#aircraftBaseFilter").addEventListener("change", renderAircraft);
$("#aircraftStatusFilter").addEventListener("change", renderAircraft);
$("#aircraftForm").addEventListener("submit", saveAircraft);
$("#deleteAircraft").addEventListener("click", removeAircraft);
$("#addHandover").addEventListener("click", () => openHandoverDialog());
$("#handoverShiftFilter").addEventListener("change", renderHandovers);
$("#handoverForm").addEventListener("submit", saveHandover);
$("#deleteHandover").addEventListener("click", removeHandover);
$("#shiftStatusCard").addEventListener("click", () => {
  document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === "passagem"));
  openModule("passagem");
});
$("#notificationButton").addEventListener("click", () => {
  document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === "passagem"));
  openModule("passagem");
});
$("#helpButton").addEventListener("click", () => $("#helpDialog").showModal());
$("#closeHelp").addEventListener("click", () => $("#helpDialog").close());
document.querySelectorAll("[data-help-target]").forEach(button => button.addEventListener("click", () => {
  $("#helpDialog").close();
  const target = button.dataset.helpTarget;
  document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === target));
  openModule(target);
}));
$("#openAircraftDashboard").addEventListener("click", () => {
  document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === "aeronaves"));
  openModule("aeronaves");
});
$("#openInstructorsDashboard").addEventListener("click", () => {
  document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === "instrutores"));
  openModule("instrutores");
});
$("#repeatArchivedSearch").addEventListener("click", () => {
  if (!archivedQuestion) return;
  const question = archivedQuestion;
  showView(homeView, "Regras e procedimentos");
  input.value = question;
  searchBox.classList.add("has-value");
  search(question);
});
$("#authForm").addEventListener("submit", async event => {
  event.preventDefault();
  const button = $("#authSubmit");
  button.disabled = true;
  $("#authError").classList.add("hidden");
  try {
    const username = $("#authUsername").value;
    const password = $("#authPassword").value;
    if (event.currentTarget.dataset.mode === "setup") {
      const response = await nativeFetch(`${window.location.origin}/api/auth/setup`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          display_name: $("#authDisplayName").value,
          username,
          password,
          setup_token: $("#authSetupToken").value,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Não foi possível criar o administrador.");
    }
    await loginWithCredentials(username, password);
  } catch (error) {
    $("#authError").textContent = error.message;
    $("#authError").classList.remove("hidden");
  } finally { button.disabled = false; }
});
$("#addUser").addEventListener("click", () => openUserDialog());
$("#userForm").addEventListener("submit", saveUser);
$("#resetUserPassword").addEventListener("click", async () => {
  const id = $("#userId").value;
  const password = window.prompt("Digite a nova senha temporária:");
  if (!password) return;
  try {
    $("#userFormError").classList.add("hidden");
    const response = await apiFetch(`${window.location.origin}/api/users/${id}/reset-password`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password, admin_edit_token: $("#userEditToken").value }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Não foi possível redefinir a senha.");
    $("#userDialog").close(); toast("Senha temporária definida. O usuário deverá alterá-la no próximo acesso.");
  } catch (error) {
    $("#userFormError").textContent = error.message;
    $("#userFormError").classList.remove("hidden");
  }
});
$("#accountButton").addEventListener("click", () => $("#accountDialog").showModal());
$("#closeAccount").addEventListener("click", () => $("#accountDialog").close());
$("#changePasswordForm").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const response = await apiFetch(`${window.location.origin}/api/auth/change-password`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: $("#currentPassword").value, new_password: $("#newPassword").value }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Não foi possível alterar a senha.");
    currentUser.must_change_password = false;
    event.currentTarget.reset(); $("#accountDialog").close(); bootstrapPortal(); toast("Senha alterada com sucesso.");
  } catch (error) { toast(error.message); }
});
$("#logoutButton").addEventListener("click", async () => {
  try { await apiFetch(`${window.location.origin}/api/auth/logout`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); } catch {}
  currentUser = null; csrfToken = ""; $("#accountDialog").close(); showAuthGate(false);
});
function toast(message) { const element = $("#toast"); element.textContent = message; element.classList.add("show"); setTimeout(() => element.classList.remove("show"), 2800); }
initializeAuth();
