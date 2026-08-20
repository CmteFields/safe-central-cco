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
  aeronaves: ["✈", "Aeronaves e manutenção", "Este módulo exibirá situação da frota, horas, vencimentos, limitações e indisponibilidades de manutenção."],
  manutencao: ["◇", "Manutenção", "Acompanhamento de inspeções, vencimentos, discrepâncias e retorno ao serviço será integrado aqui."],
  restricoes: ["!", "Restrições operacionais", "Centralização de restrições temporárias por aeródromo, base, aeronave, instrutor e aluno."],
  consulta: ["⌕", "Consultar base", "Use a pesquisa da visão geral para consultar as primeiras regras já validadas."],
};

const $ = (selector) => document.querySelector(selector);
function setDialogMessage(selector, message = "", kind = "error") {
  const element = $(selector);
  if (!element) return;
  element.textContent = message;
  element.classList.toggle("hidden", !message);
  element.classList.toggle("notice", Boolean(message) && kind === "notice");
}

const homeView = $("#homeView");
const answerView = $("#answerView");
const moduleView = $("#moduleView");
const aircraftView = $("#aircraftView");
const handoverView = $("#handoverView");
const reportsView = $("#reportsView");
const ruleManagementView = $("#ruleManagementView");
const usersView = $("#usersView");
const activityView = $("#activityView");
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
let aircraft = [];
let aircraftLoaded = false;
let operationalBases = [];
let basesPromise = null;
let handovers = [];
let handoverSummary = { pending: 0, in_progress: 0, completed: 0, information: 0 };
let handoverActiveCycleId = null;
let handoverHistoryTotal = 0;
let handoversLoaded = false;
let reports = [];
let reportsLoaded = false;
let reportAssignees = [];
let unreviewedRules = [];
let pendingApprovalRules = [];
let approvedRules = [];
let knowledgeGapItems = [];
let rulesLoaded = false;
let activeRulesTab = "unreviewed";
let currentSourceUrl = "";
let users = [];
let usersLoaded = false;
let portalActivity = [];
let activityLoaded = false;
let currentActivityArea = "Regras e procedimentos";

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
  [homeView, answerView, moduleView, aircraftView, handoverView, reportsView, ruleManagementView, usersView, activityView].forEach(item => item.classList.add("hidden"));
  view.classList.remove("hidden");
  $("#pageName").textContent = name;
  currentActivityArea = name;
  if (currentUser && csrfToken) pingPortalActivity(name);
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

function preferredClaimIds(query) {
  const text = normalizeText(query);
  const ids = [];
  const prefer = (...values) => values.forEach(value => { if (!ids.includes(value)) ids.push(value); });
  const hasAny = values => values.some(value => text.includes(value));

  const medical = text.includes("cma") || text.includes("certificado medico");
  if (medical && hasAny(["extens", "prorrog", "tolerancia", "30 dias", "validade"])) {
    prefer("claim_rbac61_tolerancia_habilitacao_nao_prorroga_cma", "claim_rbac61_cma_vencido_impede_prerrogativas");
  } else if (medical && hasAny(["voar", "voo", "operar", "sem cma", "vencid", "valido"])) {
    prefer("claim_rbac61_cma_vencido_impede_prerrogativas", "claim_rbac61_tolerancia_habilitacao_nao_prorroga_cma");
  }
  if (text.includes("cavok") && hasAny(["acess", "entr", "login", "senha", "link", "portal", "cadastro"])) {
    prefer("claim_cavok_acesso_pessoal_aluno");
  }
  if (hasAny(["inva", "instrutor", "professor de voo"]) && hasAny(["escolh", "prefer", "troc", "substitu", "voar com", "escala"])) {
    prefer("claim_mip_substituicao_instrutor_solicitada_administracao");
  }
  if (hasAny(["base", "sjk", "cpq", "sao jose", "campinas"]) && hasAny(["troc", "mud", "transfer", "alter", "migr"])) {
    prefer("claim_rg006_troca_base_aluno");
  }
  if (text.includes("barra") && hasAny(["prior", "primeira", "segunda", "cheque", "missao", "critica", "ordem"])) {
    prefer("claim_rg010_prioridade_barras_missoes_criticas");
  }
  if (text.includes("monitor") && text.includes("nav") && hasAny(["fase ap", "aperfeicoamento", "ap01", "ap02", "ap03", "ap04", "ap05"])) {
    prefer("claim_mgop_monitoria_nav_durante_fase_ap");
  }
  if (text.includes("nav03") && text.includes("nav02") && hasAny(["antes", "ordem", "sequencia", "adiant", "preced"])) {
    prefer("claim_ppap001k_nav03_pode_anteceder_nav02");
  } else if (text.includes("sequencia") && hasAny(["ppa", "pp", "missoes", "missao"])) {
    prefer("claim_ppap001k_sequencia_completa_missoes");
  }
  const recencyDays = [...text.matchAll(/\b(\d{1,3})\s*dias?\b/g)].some(match => Number(match[1]) >= 30);
  if ((text.includes("trinta dias") || recencyDays) && hasAny(["sem solo", "sem voar solo", "ap05", "ultimo solo"])) {
    prefer("claim_bops054_sem_solo_30_dias_novo_endosso", "claim_bops054_readaptacao_90_dias");
  }
  if (text.includes("solo") && hasAny(["mae", "pai", "famil", "acompanhante", "passageiro", "esposa", "marido"])) {
    if (hasAny(["levar", "embarcar", "a bordo", "voar com", "para voar", "passageiro"])) {
      prefer("claim_mip_acompanhante_proibido_solo_pp", "claim_mip_familia_pode_acompanhar_evento_solo_em_terra");
    } else if (hasAny(["assistir", "acompanhar", "presenciar", "ver", "evento", "terra", "patio"])) {
      prefer("claim_mip_familia_pode_acompanhar_evento_solo_em_terra", "claim_mip_acompanhante_proibido_solo_pp");
    }
  }
  return ids;
}

function findGraphResults(query) {
  const tokens = tokenize(query);
  if (!tokens.length) return [];
  const preferredIds = preferredClaimIds(query);
  const medicalIntent = tokens.includes("cma") || normalizeText(query).includes("certificado medico");
  const medicalOperationIntent = medicalIntent && tokens.some(token => ["voar", "voo", "operar", "operacao", "prerrogativas", "valido", "vencido", "sem"].includes(token));
  return [...graphIndex.claims.map(item => ({ ...item, kind: "Regra confirmada" })), ...graphIndex.documents.map(item => ({ ...item, kind: "Documento relacionado" }))]
    .filter(item => {
      if (!medicalIntent) return true;
      const medicalText = normalizeText(`${item.label || ""} ${item.code || ""} ${item.source || ""} ${item.appliesTo || ""}`);
      return medicalText.includes("cma") || medicalText.includes("certificado medico");
    })
    .map(item => {
      const medicalText = normalizeText(`${item.label || ""} ${item.appliesTo || ""}`);
      const canonicalBoost = item.operatorAnswer ? 50 : 0;
      const preferredPosition = preferredIds.indexOf(item.id);
      const contextualBoost = preferredPosition >= 0 ? Math.max(520, 650 - (preferredPosition * 40)) : 0;
      const enrollmentPenalty = medicalOperationIntent && medicalText.includes("matricula") ? -15 : 0;
      const intentBoost = medicalIntent && !medicalOperationIntent && medicalText.includes("matricula") ? 8 : 0;
      return { ...item, score: scoreRecord(item, tokens) + canonicalBoost + contextualBoost + enrollmentPenalty + intentBoost };
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
  const canonical = confirmed.find(item => item.operatorAnswer);
  const primary = canonical || confirmed[0] || results[0];
  const relatedResults = results.filter(item => item.id !== primary.id);
  const related = relatedResults.slice(0, 4).map(item => `<div class="answer-highlight"><strong>${escapeHtml(item.label)}</strong><br><small>${escapeHtml(item.kind)}${item.code ? ` · ${escapeHtml(item.code)}` : ""}${item.location ? ` · ${escapeHtml(item.location)}` : ""}</small></div>`).join("");
  if (canonical) {
    return {
      question: query,
      answer: `<p>${escapeHtml(canonical.operatorAnswer).replace(/\n/g, "<br>")}</p><div class="answer-highlight"><strong>Resposta confirmada pela base SAFE.</strong><br><small>Resposta operacional curada e disponível mesmo durante indisponibilidade da IA.</small></div>`,
      source: canonical.code || canonical.label,
      detail: `${canonical.location || "Regra confirmada"} · Índice confirmado local`,
      relations: [[
        "REGRA CONFIRMADA",
        canonical.label,
        canonical.code || canonical.location || "Base SAFE",
      ], ...relatedResults.slice(0, 2).map(item => [
        item.kind.toUpperCase(),
        item.label,
        item.code || item.source || "Grafo SAFE",
      ])],
    };
  }
  return {
    question: query,
    answer: `<div class="answer-highlight provisional-answer"><strong>Busca local inconclusiva.</strong><br><small>A inteligência artificial não respondeu e o índice local encontrou apenas evidências relacionadas. Não as trate como resposta à pergunta.</small></div><p>Evidência relacionada:</p><div class="answer-highlight"><strong>${escapeHtml(primary.label)}</strong><br><small>${primary.code ? escapeHtml(primary.code) : "Documento SAFE"}${primary.location ? ` · ${escapeHtml(primary.location)}` : ""}</small></div>${related ? `<p><strong>Outras evidências relacionadas:</strong></p>${related}` : ""}`,
    source: "Busca local inconclusiva",
    detail: `Evidências sem interpretação conclusiva · ${primary.source || "Grafo SAFE"}${primary.location ? ` · ${primary.location}` : ""}`,
    provisional: true,
    relations: [primary, ...relatedResults].slice(0, 3).map(item => ["EVIDÊNCIA RELACIONADA", item.label, item.code || item.source || "Grafo SAFE"])
  };
}

function apiResultAnswer(query, result) {
  const confidenceLabels = { high: "Alta confiança", medium: "Confiança moderada", low: "Baixa confiança" };
  const sources = result.sources || [];
  const provisional = ["unreviewed", "pending_approval", "pending_review"].includes(result.knowledge_status) || result.provisional;
  const primary = sources[0];
  const aiDiagnostic = [result.local_error, result.external_error].filter(Boolean).join(" | ");
  return {
    question: query,
    answer: `${provisional ? `<div class="answer-highlight provisional-answer"><strong>Resposta provisória — ainda não aprovada.</strong><br><small>A pergunta foi registrada automaticamente na Gestão de regras como Não revisada${result.candidate_id ? `, item #${escapeHtml(result.candidate_id)}` : ""}. Não use esta proposta como regra interna definitiva.</small></div>` : ""}<p>${escapeHtml(result.answer).replace(/\n/g, "<br>")}</p><div class="answer-highlight"><strong>${confidenceLabels[result.confidence] || "Confiança não informada"}</strong><br><small>Consulta ${escapeHtml(result.query_id || "")} · ${result.candidate_relations_count || 0} nova(s) relação(ões) candidata(s)</small></div>${aiDiagnostic ? `<div class="answer-highlight provisional-answer"><strong>Diagnóstico da IA para supervisão</strong><br><small>${escapeHtml(aiDiagnostic)}</small></div>` : ""}`,
    source: primary?.code || primary?.label || (provisional ? "Pesquisa pendente de aprovação" : "Grafo SAFE + Gemini"),
    detail: primary ? `${primary.location || "Localização não informada"}` : "Nenhuma evidência suficiente localizada",
    sourceUrl: primary?.url || "",
    provisional,
    relations: sources.slice(0, 5).map(item => [item.kind === "confirmed_claim" ? "REGRA CONFIRMADA" : item.kind === "external_source" ? "FONTE EXTERNA · PROVISÓRIA" : "DOCUMENTO", item.label, item.code || item.location || "Grafo SAFE", item.url || ""]),
  };
}

async function askApi(query) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 150000);
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

function clearKnowledgeSearch() {
  input.value = "";
  searchBox.classList.remove("has-value");
  closeSearchSuggestions();
}

function startNewSearch() {
  archivedQuestion = "";
  clearKnowledgeSearch();
  showView(homeView, "Regras e procedimentos");
  window.requestAnimationFrame(() => input.focus());
}

function showAnswer(item, originalQuestion, options = {}) {
  clearKnowledgeSearch();
  $("#answerQuestion").textContent = originalQuestion || item.question;
  $("#answerBody").innerHTML = item.answer;
  $("#sourceTitle").textContent = item.source;
  $("#sourceDetail").textContent = item.detail;
  currentSourceUrl = item.sourceUrl || "";
  $("#sourceButton").disabled = !currentSourceUrl;
  $("#sourceButton").textContent = currentSourceUrl ? "Ver fonte" : "Fonte interna";
  $("#relationList").innerHTML = item.relations.map(r => `<div class="relation"><small>${r[0]}</small><strong>${r[1]}</strong><span>${r[2]}</span>${r[3] ? `<a href="${escapeHtml(r[3])}" target="_blank" rel="noopener noreferrer">Abrir fonte oficial ↗</a>` : ""}</div>`).join("");
  const provisional = Boolean(item.provisional);
  $("#answerConfidence").classList.toggle("provisional", provisional);
  $("#answerConfidenceIcon").textContent = provisional ? "!" : "✓";
  $("#answerConfidenceTitle").textContent = provisional ? "Resposta provisória" : "Resposta confirmada";
  $("#answerConfidenceDetail").textContent = provisional ? "Aguardando validação humana" : "Baseada em documento vigente";
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
    if (hasRole("admin", "supervisor") && apiResult.provisional) loadRules();
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

function formatInstructorDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function aircraftStatusClass(status) {
  const value = normalizeText(status);
  if (value.includes("manuten")) return "maintenance";
  if (value.includes("fora") || value.includes("inativ")) return "inactive";
  return "";
}

function fillAircraftFilters() {
  const selectedBase = $("#aircraftBaseFilter").value;
  const selectedFleetStatus = $("#aircraftFleetFilter").value;
  const selectedStatus = $("#aircraftStatusFilter").value;
  const bases = [...new Set(aircraft.map(item => item.base))].sort();
  const fleetStatuses = [...new Set(aircraft.map(item => item.fleet_status))].sort();
  const statuses = [...new Set(aircraft.map(item => item.status))].sort();
  $("#aircraftBaseFilter").innerHTML = `<option value="">Todas as bases</option>${bases.map(value => `<option>${escapeHtml(value)}</option>`).join("")}`;
  $("#aircraftFleetFilter").innerHTML = `<option value="">Ativas e inativas</option>${fleetStatuses.map(value => `<option>${escapeHtml(value)}</option>`).join("")}`;
  $("#aircraftStatusFilter").innerHTML = `<option value="">Todos os status</option>${statuses.map(value => `<option>${escapeHtml(value)}</option>`).join("")}`;
  $("#aircraftBaseFilter").value = bases.includes(selectedBase) ? selectedBase : "";
  $("#aircraftFleetFilter").value = fleetStatuses.includes(selectedFleetStatus) ? selectedFleetStatus : "";
  $("#aircraftStatusFilter").value = statuses.includes(selectedStatus) ? selectedStatus : "";
}

function renderRestrictedAircraftDashboard() {
  const box = $("#restrictedAircraftList");
  if (!box) return;
  const restricted = aircraft.filter(
    item => item.fleet_status === "Ativa" && item.status !== "Operacional"
  );
  if (!restricted.length) {
    box.innerHTML = `<div class="dashboard-clear"><span>✓</span>Nenhuma aeronave ativa possui restrição operacional.</div>`;
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
  const fleetStatus = $("#aircraftFleetFilter").value;
  const status = $("#aircraftStatusFilter").value;
  const canEditAircraft = hasRole("admin", "supervisor");
  const visible = aircraft.filter(item => {
    const searchable = normalizeText(`${item.model} ${item.registration} ${item.base} ${item.fleet_status} ${item.status} ${item.operation_type} ${item.active_restrictions} ${item.temporary_restrictions}`);
    return (!query || searchable.includes(query))
      && (!base || item.base === base)
      && (!fleetStatus || item.fleet_status === fleetStatus)
      && (!status || item.status === status);
  });
  $("#aircraftTotal").textContent = `${visible.length} de ${aircraft.length} aeronave${aircraft.length === 1 ? "" : "s"}`;
  $("#aircraftRows").innerHTML = visible.length ? visible.map(item => `
    <tr>
      <td><span class="instructor-name">${escapeHtml(item.model)}</span></td>
      <td><span class="registration">${escapeHtml(item.registration)}</span></td>
      <td><span class="base-badge ${item.base === "CPQ" ? "cpq" : ""}">${escapeHtml(item.base)}</span></td>
      <td class="aircraft-situation-cell">
        <div><small>FROTA</small><span class="status-badge ${item.fleet_status === "Inativa" ? "inactive" : ""}">${escapeHtml(item.fleet_status)}</span></div>
        <div><small>OPERAÇÃO</small><span class="status-badge ${aircraftStatusClass(item.status)}">${escapeHtml(item.status)}</span></div>
      </td>
      <td>${escapeHtml(item.operation_type)}</td>
      <td class="restriction-cell">
        <strong>${escapeHtml(item.active_restrictions)}</strong>
        <div class="temporary-restriction ${normalizeText(item.temporary_restrictions) === "nenhuma" ? "is-clear" : "has-restriction"}">
          <span>${normalizeText(item.temporary_restrictions) === "nenhuma" ? "✓" : "!"}</span>
          <div><b>${normalizeText(item.temporary_restrictions) === "nenhuma" ? "OK · sem restrição temporária" : "Tem restrição temporária"}</b>${normalizeText(item.temporary_restrictions) !== "nenhuma" ? `<small>${escapeHtml(item.temporary_restrictions)}${item.restriction_date ? ` · ${escapeHtml(item.restriction_date.split("-").reverse().join("/"))}` : ""}</small>` : ""}</div>
        </div>
      </td>
      <td class="updated-cell">${formatInstructorDate(item.updated_at)}</td>
      <td class="row-actions aircraft-actions">${canEditAircraft
        ? `<button class="edit-aircraft-button" data-aircraft-id="${item.id}" aria-label="Editar ${escapeHtml(item.registration)}"><span>✎</span> Editar</button>`
        : `<span class="aircraft-readonly">Somente leitura</span>`}</td>
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
  setDialogMessage("#aircraftFormError");
  $("#aircraftId").value = item?.id || "";
  $("#aircraftModel").value = item?.model || "";
  $("#aircraftRegistration").value = item?.registration || "";
  renderBaseSelect($("#aircraftBase"), true, item?.base || "Não informada");
  $("#aircraftFleetStatus").value = item?.fleet_status || "Ativa";
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
    base: $("#aircraftBase").value, fleet_status: $("#aircraftFleetStatus").value,
    status: $("#aircraftStatus").value,
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
  } catch (error) { setDialogMessage("#aircraftFormError", error.message); }
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
  } catch (error) { setDialogMessage("#aircraftFormError", error.message); }
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

function currentHandoverRoute() {
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  if (minutes < 14 * 60) return { origin: "T1", target: "T2" };
  if (minutes < 18 * 60) return { origin: "T2", target: "T3" };
  return { origin: "T3", target: "T1" };
}

function findHandoverItem(id) {
  for (const cycle of handovers) {
    const item = cycle.items.find(value => value.id === id);
    if (item) return { item, cycle };
  }
  return {};
}

function handoverActionButton(action, id, label, className = "") {
  return `<button class="${className}" data-handover-action="${action}" data-handover-id="${id}">${label}</button>`;
}

function handoverCard(item, cycle) {
  const canOperate = hasRole("admin", "supervisor", "operator");
  const canEdit = canOperate && cycle.state === "draft" && !item.carried_from_id;
  const canTransition = canOperate && item.is_latest_root;
  const actions = [];
  if (canEdit) actions.push(`<button data-handover-edit="${item.id}">Editar</button>`);
  if (canTransition && item.item_type === "Pendência") {
    if (item.status === "Pendente") actions.push(handoverActionButton("assume", item.id, "Assumir", "advance"));
    if (["Pendente", "Em andamento"].includes(item.status)) actions.push(handoverActionButton("complete", item.id, "Concluir", "advance"));
    if (item.status === "Concluída") actions.push(handoverActionButton("reopen", item.id, "Reabrir"));
    actions.push(handoverActionButton("assign", item.id, "Responsável"));
  }
  if (canTransition) actions.push(handoverActionButton("comment", item.id, "Comentar"));
  return `<article class="handover-card priority-${normalizeText(item.priority)}">
    <div class="handover-card-top"><span class="handover-type type-${normalizeText(item.item_type)}">${escapeHtml(item.item_type)}</span><span class="priority-label">${escapeHtml(item.priority)}</span><span class="handover-status status-${normalizeText(item.status)}">${escapeHtml(item.status)}</span><span class="handover-card-time">${formatInstructorDate(item.updated_at)}</span></div>
    <p>${escapeHtml(item.message)}</p>
    <div class="handover-item-meta"><span>Deixado por <strong>${escapeHtml(item.author)}</strong></span>${item.assignee ? `<span>Responsável: <strong>${escapeHtml(item.assignee)}</strong></span>` : ""}${item.carried_from_id ? '<span class="carried-tag">↻ Pendência trazida da passagem anterior</span>' : ""}</div>
    ${item.completion_note ? `<div class="handover-completion"><strong>Conclusão por ${escapeHtml(item.completed_by)}</strong>${escapeHtml(item.completion_note)}</div>` : ""}
    ${actions.length ? `<div class="handover-card-actions">${actions.join("")}</div>` : ""}
  </article>`;
}

function handoverEvents(cycle) {
  if (!cycle.events.length) return "";
  return `<details class="handover-audit"><summary>Histórico e auditoria (${cycle.events.length})</summary><div>${cycle.events.map(event => {
    const note = event.details?.note || event.details?.assignee || "";
    return `<p><strong>${escapeHtml(event.action)}</strong> · ${escapeHtml(event.actor_name || "Sistema")} · ${formatInstructorDate(event.created_at)}${note ? `<br><span>${escapeHtml(note)}</span>` : ""}</p>`;
  }).join("")}</div></details>`;
}

function handoverItemGroup(title, items, cycle, className = "") {
  if (!items.length) return "";
  return `<div class="handover-item-group ${className}"><h4>${title}<span>${items.length}</span></h4>${items.map(item => handoverCard(item, cycle)).join("")}</div>`;
}

function handoverBaseSection(base, cycle) {
  const baseDescriptions = {
    Geral: "Duas bases ou CCO",
    SDAM: "Campo dos Amarais · Campinas",
    SBSJ: "São José dos Campos",
  };
  const items = cycle.items.filter(item => item.base_scope === base);
  const openItems = items.filter(item => item.item_type === "Pendência" && item.status !== "Concluída");
  const informationItems = items.filter(item => item.item_type === "Informação");
  const completedItems = items.filter(item => item.item_type === "Pendência" && item.status === "Concluída");
  const content = [
    handoverItemGroup("Pendências abertas", openItems, cycle, "handover-open-group"),
    handoverItemGroup("Informações do turno", informationItems, cycle, "handover-information-group"),
    completedItems.length ? `<details class="handover-completed-group"><summary>Concluídas neste ciclo <span>${completedItems.length}</span></summary>${completedItems.map(item => handoverCard(item, cycle)).join("")}</details>` : "",
  ].filter(Boolean).join("");
  return `<section class="handover-base-section base-${base.toLowerCase()}"><div class="handover-base-head"><div><strong>${base}</strong><small>${baseDescriptions[base]}</small></div><span>${items.length}</span></div>${content || '<div class="handover-empty">Nenhuma anotação para esta seção.</div>'}</section>`;
}

function handoverCycle(cycle, { expanded = false, history = false } = {}) {
  const canOperate = hasRole("admin", "supervisor", "operator");
  const bases = ["Geral", "SDAM", "SBSJ"];
  const controls = cycle.state === "draft" && canOperate
    ? `<button class="primary-action" data-handover-publish="${cycle.id}">Publicar passagem</button>`
    : cycle.state === "awaiting_receipt" && canOperate
      ? `<button class="primary-action" data-handover-receive="${cycle.id}">Confirmar recebimento</button>` : "";
  const body = `<div class="handover-base-grid">${bases.map(base => handoverBaseSection(base, cycle)).join("")}</div>${handoverEvents(cycle)}`;
  return `<article class="handover-cycle state-${cycle.state}${history ? " historical-cycle" : " active-cycle"}">
    <div class="handover-cycle-head"><div><div class="handover-cycle-route">${cycle.origin_shift} → ${cycle.target_shift}<span>${escapeHtml(cycle.state_label)}</span></div><p>${cycle.state === "draft" ? `Em elaboração por ${escapeHtml(cycle.created_by_name || "Operador")}` : `Publicada por ${escapeHtml(cycle.published_by_name || "Operador")} · ${formatInstructorDate(cycle.published_at)}`}${cycle.received_at ? ` · Recebida por ${escapeHtml(cycle.received_by_name)} em ${formatInstructorDate(cycle.received_at)}` : ""}</p></div><div class="handover-cycle-controls"><span>${cycle.items.length} anotação(ões)</span>${controls}</div></div>
    ${expanded ? body : `<details class="handover-history-cycle"><summary>Visualizar esta passagem</summary>${body}</details>`}
  </article>`;
}

function bindHandoverActions() {
  document.querySelectorAll("[data-handover-edit]").forEach(button => button.addEventListener("click", () => {
    const found = findHandoverItem(Number(button.dataset.handoverEdit));
    openHandoverDialog(found.item, found.cycle);
  }));
  document.querySelectorAll("[data-handover-action]").forEach(button => button.addEventListener("click", () => transitionHandover(Number(button.dataset.handoverId), button.dataset.handoverAction)));
  document.querySelectorAll("[data-handover-publish]").forEach(button => button.addEventListener("click", () => publishHandover(Number(button.dataset.handoverPublish))));
  document.querySelectorAll("[data-handover-receive]").forEach(button => button.addEventListener("click", () => receiveHandover(Number(button.dataset.handoverReceive))));
}

function renderHandovers() {
  const target = $("#handoverShiftFilter").value;
  const visible = handovers.filter(cycle => !target || cycle.target_shift === target);
  const active = visible.find(cycle => cycle.is_active || cycle.id === handoverActiveCycleId);
  const history = visible.filter(cycle => !active || cycle.id !== active.id);
  $("#handoverPendingCount").textContent = handoverSummary.pending;
  $("#handoverProgressCount").textContent = handoverSummary.in_progress;
  $("#handoverInfoCount").textContent = handoverSummary.information;
  $("#handoverDoneCount").textContent = handoverSummary.completed;
  const openCount = handoverSummary.pending + handoverSummary.in_progress;
  $("#handoverNavCount").textContent = openCount;
  updateNotificationBadge();
  const current = `<section class="handover-view-section handover-current-section"><div class="handover-section-heading"><div><span>AGORA</span><h2>Passagem atual</h2></div><small>Os indicadores acima consideram somente este ciclo.</small></div>${active ? handoverCycle(active, { expanded: true }) : '<div class="table-message">Nenhuma passagem atual para o destino selecionado.</div>'}</section>`;
  const historyCount = target ? history.length : handoverHistoryTotal;
  const archived = history.length
    ? history.map(cycle => handoverCycle(cycle, { history: true })).join("")
    : '<div class="table-message">Nenhuma passagem anterior para o destino selecionado.</div>';
  $("#handoverBoard").innerHTML = `${current}<details class="handover-history"><summary><span><strong>Histórico de passagens</strong><small>Consulte ciclos anteriores sem misturá-los à operação atual.</small></span><b>${historyCount}</b></summary><div class="handover-history-list">${archived}</div></details>`;
  bindHandoverActions();
}

async function loadHandovers() {
  try {
    const data = await handoverRequest();
    handovers = data.cycles || [];
    handoverSummary = data.summary || handoverSummary;
    handoverActiveCycleId = data.active_cycle_id ?? null;
    handoverHistoryTotal = data.history_total ?? Math.max(0, handovers.length - (handoverActiveCycleId ? 1 : 0));
    handoversLoaded = true;
    renderHandovers();
  } catch (error) {
    $("#handoverBoard").innerHTML = `<div class="table-message">Não foi possível carregar as passagens de turno.</div>`;
    toast(error.message);
  }
}

function openHandoverDialog(item = null, cycle = null) {
  $("#handoverForm").reset();
  setDialogMessage("#handoverFormError");
  const activeDraft = handovers.find(value => value.state === "draft");
  const route = activeDraft ? { origin: activeDraft.origin_shift, target: activeDraft.target_shift } : currentHandoverRoute();
  $("#handoverId").value = item?.id || "";
  $("#handoverOrigin").value = item?.origin_shift || route.origin;
  $("#handoverTarget").value = item?.target_shift || route.target;
  $("#handoverBase").value = item?.base_scope || "";
  $("#handoverType").value = item?.item_type || "Pendência";
  $("#handoverPriority").value = item?.priority || "Normal";
  $("#handoverAssignee").value = item?.assignee || "";
  $("#handoverMessage").value = item?.message || "";
  $("#handoverOrigin").disabled = Boolean(activeDraft || item);
  $("#handoverTarget").disabled = Boolean(activeDraft || item);
  $("#handoverDialogTitle").textContent = item ? "Editar anotação" : "Nova anotação da passagem";
  $("#deleteHandover").classList.toggle("hidden", !item || cycle?.state !== "draft");
  $("#handoverDialog").showModal();
  setTimeout(() => $("#handoverMessage").focus(), 50);
}

function handoverPayload() {
  return {
    origin_shift: $("#handoverOrigin").value, target_shift: $("#handoverTarget").value,
    base_scope: $("#handoverBase").value, item_type: $("#handoverType").value,
    priority: $("#handoverPriority").value, assignee: $("#handoverAssignee").value,
    message: $("#handoverMessage").value,
  };
}

function handoverBaseWarning(payload) {
  if (!payload.base_scope || payload.base_scope === "Geral") return "";
  const message = normalizeText(payload.message);
  const mentionsSbsj = /\bsbsj\b|sao jose/.test(message);
  const mentionsSdam = /\bsdam\b|amarais|campinas/.test(message);
  if (mentionsSbsj === mentionsSdam) return "";
  if (payload.base_scope === "SBSJ" && mentionsSdam) {
    return "A mensagem menciona SDAM/Campinas, mas a ação foi classificada como SBSJ. Deseja manter essa classificação?";
  }
  if (payload.base_scope === "SDAM" && mentionsSbsj) {
    return "A mensagem menciona SBSJ/São José dos Campos, mas a ação foi classificada como SDAM. Deseja manter essa classificação?";
  }
  return "";
}

async function saveHandover(event) {
  event.preventDefault();
  const id = $("#handoverId").value;
  const payload = handoverPayload();
  const baseWarning = handoverBaseWarning(payload);
  if (baseWarning && !window.confirm(baseWarning)) return;
  const button = $("#saveHandover");
  button.disabled = true;
  try {
    await handoverRequest(id ? `/${id}` : "", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) });
    $("#handoverDialog").close();
    await loadHandovers();
    toast(id ? "Anotação atualizada." : "Anotação incluída na passagem em elaboração.");
  } catch (error) { setDialogMessage("#handoverFormError", error.message); }
  finally { button.disabled = false; }
}

async function transitionHandover(id, action) {
  const labels = { complete: "Informe como a pendência foi concluída:", reopen: "Informe por que a pendência será reaberta:", comment: "Digite o comentário:", assign: "Informe o responsável (deixe vazio para remover):" };
  let note = "";
  let assignee = "";
  if (labels[action]) {
    const value = window.prompt(labels[action]);
    if (value === null) return;
    if (action === "assign") assignee = value.trim(); else note = value.trim();
    if (["complete", "reopen", "comment"].includes(action) && !note) { toast("A observação é obrigatória."); return; }
  }
  try {
    const payload = { action, note, assignee };
    if (action === "reopen") {
      const draft = handovers.find(cycle => cycle.state === "draft");
      const route = draft || currentHandoverRoute();
      payload.origin_shift = route.origin_shift || route.origin;
      payload.target_shift = route.target_shift || route.target;
    }
    await handoverRequest(`/${id}/actions`, { method: "POST", body: JSON.stringify(payload) });
    await loadHandovers();
    toast({ assume: "Pendência assumida.", complete: "Pendência concluída.", reopen: "Pendência reaberta.", assign: "Responsável atualizado.", comment: "Comentário registrado." }[action]);
  } catch (error) { toast(error.message); }
}

async function publishHandover(id) {
  if (!window.confirm("Publicar esta passagem? O conteúdo original não poderá mais ser editado.")) return;
  try { await handoverRequest(`/cycles/${id}/publish`, { method: "POST", body: "{}" }); await loadHandovers(); toast("Passagem publicada e aguardando recebimento."); }
  catch (error) { toast(error.message); }
}

async function receiveHandover(id) {
  if (!window.confirm("Confirmar o recebimento desta passagem de turno?")) return;
  try { await handoverRequest(`/cycles/${id}/receive`, { method: "POST", body: "{}" }); await loadHandovers(); toast("Recebimento confirmado."); }
  catch (error) { toast(error.message); }
}

async function removeHandover() {
  const id = Number($("#handoverId").value);
  if (!id || !window.confirm("Excluir esta anotação da passagem em elaboração?")) return;
  const button = $("#deleteHandover");
  button.disabled = true;
  try { await handoverRequest(`/${id}`, { method: "DELETE" }); $("#handoverDialog").close(); await loadHandovers(); toast("Anotação excluída."); }
  catch (error) { setDialogMessage("#handoverFormError", error.message); }
  finally { button.disabled = false; }
}

async function reportRequest(path = "", options = {}) {
  const response = await apiFetch(`${window.location.origin}/api/reports${path}`, {
    ...options,
    headers: options.body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Erro HTTP ${response.status}`);
  return data;
}

function reportStatusClass(status) {
  if (status === "Em análise") return "analysis";
  if (status === "Resolvido") return "resolved";
  if (status === "Descartado") return "discarded";
  return "open";
}

function reportRuleBadge(item) {
  if (!item.rule_candidate) return "";
  const statusClass = item.rule_candidate.status === "approved" ? "approved" : item.rule_candidate.status === "rejected" ? "rejected" : "pending";
  return `<span class="report-rule-status ${statusClass}">Regra #${item.rule_candidate.id} · ${escapeHtml(item.rule_candidate.status_label)}</span>`;
}

function reportCard(item) {
  const canManage = hasRole("admin", "supervisor");
  const canEditOwn = hasRole("operator") && item.reporter_username === currentUser.username && item.status === "Aberto";
  return `<article class="report-card priority-${normalizeText(item.priority)}">
    <div class="report-card-head">
      <span class="report-kind ${item.report_type === "question" ? "question" : ""}">${escapeHtml(item.type_label)}</span>
      <span class="report-status ${reportStatusClass(item.status)}">${escapeHtml(item.status)}</span>
      <span class="report-priority">${escapeHtml(item.priority)}</span>
      <span class="report-time">${formatInstructorDate(item.updated_at)}</span>
    </div>
    <h3>${escapeHtml(item.title)}</h3>
    <p class="report-description">${escapeHtml(item.description)}</p>
    ${item.reference ? `<div class="report-reference"><strong>REFERÊNCIA RELACIONADA</strong>${escapeHtml(item.reference)}</div>` : ""}
    ${item.resolution ? `<div class="report-resolution"><strong>TRATATIVA</strong>${escapeHtml(item.resolution)}</div>` : ""}
    <div class="report-links">${item.assignee_name ? `<span>Responsável: <strong>${escapeHtml(item.assignee_name)}</strong></span>` : "<span>Sem responsável</span>"}${reportRuleBadge(item)}</div>
    <div class="report-card-footer">
      <span>Reportado por <strong>${escapeHtml(item.reporter_name)}</strong> · ${formatInstructorDate(item.created_at)} · ${item.comments.length} comentário(s) · ${item.attachments.length} anexo(s)</span>
      <button data-report-detail="${item.id}">Detalhes</button>
      ${canEditOwn ? `<button data-report-edit="${item.id}">Editar</button>` : ""}
      ${canManage ? `<button data-report-review="${item.id}">Analisar</button>` : ""}
    </div>
  </article>`;
}

function updateNotificationBadge() {
  const handoverCount = handoverSummary.pending + handoverSummary.in_progress;
  const criticalReports = reports.filter(item => item.priority === "Crítica" && ["Aberto", "Em análise"].includes(item.status)).length;
  const total = handoverCount + criticalReports;
  $("#notificationCount").textContent = total > 99 ? "99+" : total;
  $("#notificationCount").classList.toggle("hidden", total === 0);
  $("#notificationButton").dataset.criticalReports = String(criticalReports);
  $("#notificationButton").setAttribute(
    "aria-label",
    criticalReports ? `${criticalReports} report(s) crítico(s) e ${handoverCount} passagem(ns) pendente(s)` : "Abrir pendências da passagem de turno",
  );
}

function syncReportAuthorFilter() {
  const select = $("#reportAuthorFilter");
  const selected = select.value;
  const authors = [...new Map(reports.map(item => [item.reporter_username, item.reporter_name])).entries()]
    .sort((left, right) => left[1].localeCompare(right[1], "pt-BR"));
  select.innerHTML = '<option value="">Todos</option>' + authors.map(([username, name]) => `<option value="${escapeHtml(username)}">${escapeHtml(name)}</option>`).join("");
  if (authors.some(([username]) => username === selected)) select.value = selected;
}

function renderReports() {
  const type = $("#reportTypeFilter").value;
  const status = $("#reportStatusFilter").value;
  const priority = $("#reportPriorityFilter").value;
  const author = $("#reportAuthorFilter").value;
  const dateFrom = $("#reportDateFrom").value;
  const dateTo = $("#reportDateTo").value;
  const search = normalizeText($("#reportSearch").value);
  const visible = reports.filter(item => {
    const haystack = normalizeText([item.title, item.description, item.reference, item.reporter_name, item.assignee_name, item.resolution].join(" "));
    const created = String(item.created_at).slice(0, 10);
    return (!type || item.report_type === type)
      && (!status || item.status === status)
      && (!priority || item.priority === priority)
      && (!author || item.reporter_username === author)
      && (!dateFrom || created >= dateFrom)
      && (!dateTo || created <= dateTo)
      && (!search || haystack.includes(search));
  });
  const count = value => reports.filter(item => item.status === value).length;
  $("#reportOpenCount").textContent = count("Aberto");
  $("#reportAnalysisCount").textContent = count("Em análise");
  $("#reportClosedCount").textContent = count("Resolvido") + count("Descartado");
  const openCount = count("Aberto") + count("Em análise");
  $("#reportNavCount").textContent = openCount > 99 ? "99+" : openCount;
  updateNotificationBadge();
  $("#reportList").innerHTML = visible.length
    ? visible.map(reportCard).join("")
    : `<div class="table-message">Nenhum report encontrado com estes filtros.</div>`;
  document.querySelectorAll("[data-report-review]").forEach(button => button.addEventListener("click", () => {
    openReportReview(reports.find(item => item.id === Number(button.dataset.reportReview)));
  }));
  document.querySelectorAll("[data-report-detail]").forEach(button => button.addEventListener("click", () => {
    openReportDetails(reports.find(item => item.id === Number(button.dataset.reportDetail)));
  }));
  document.querySelectorAll("[data-report-edit]").forEach(button => button.addEventListener("click", () => {
    const item = reports.find(report => report.id === Number(button.dataset.reportEdit));
    openReportDialog(item, item);
  }));
}

async function loadReports() {
  try {
    const data = await reportRequest();
    reports = data.items;
    reportAssignees = data.assignees || [];
    reportsLoaded = true;
    syncReportAuthorFilter();
    renderReports();
  } catch (error) {
    $("#reportList").innerHTML = `<div class="table-message">Não foi possível carregar os reports.</div>`;
    toast(error.message);
  }
}

function openReportDialog(prefill = {}, editing = null) {
  if (!hasRole("admin", "supervisor", "operator")) {
    toast("Seu perfil não pode registrar reports.");
    return;
  }
  $("#reportForm").reset();
  $("#reportForm").dataset.id = editing ? String(editing.id) : "";
  $("#reportFormError").classList.add("hidden");
  $("#reportDialogTitle").textContent = editing ? "Editar report aberto" : "Novo report";
  $("#reportType").value = prefill.report_type || "discrepancy";
  $("#reportType").disabled = Boolean(editing);
  $("#reportPriority").value = prefill.priority || "Normal";
  $("#reportTitle").value = prefill.title || "";
  $("#reportDescription").value = prefill.description || "";
  $("#reportReference").value = prefill.reference || "";
  $("#saveReport").textContent = editing ? "Salvar alterações" : "Enviar report";
  $("#reportDialog").showModal();
  setTimeout(() => $("#reportTitle").focus(), 50);
}

async function reportFilePayload(file) {
  if (file.size > 2 * 1024 * 1024) throw new Error(`${file.name}: o limite por anexo é 2 MB.`);
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 32768) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  }
  return { filename: file.name, content_type: file.type || "text/plain", content_base64: btoa(binary) };
}

async function uploadReportFiles(reportId, files) {
  if (files.length > 5) throw new Error("Selecione no máximo 5 anexos.");
  for (const file of files) {
    await reportRequest(`/${reportId}/attachments`, { method: "POST", body: JSON.stringify(await reportFilePayload(file)) });
  }
}

async function saveReport(event) {
  event.preventDefault();
  const button = $("#saveReport");
  const errorBox = $("#reportFormError");
  errorBox.classList.add("hidden");
  button.disabled = true;
  try {
    const reportId = Number($("#reportForm").dataset.id || 0);
    const saved = await reportRequest(reportId ? `/${reportId}` : "", {
      method: reportId ? "PUT" : "POST",
      body: JSON.stringify({
        report_type: $("#reportType").value,
        priority: $("#reportPriority").value,
        title: $("#reportTitle").value,
        description: $("#reportDescription").value,
        reference: $("#reportReference").value,
      }),
    });
    await uploadReportFiles(saved.id, [...$("#reportFiles").files]);
    await loadReports();
    reportsLoaded = true;
    if (saved.report_type === "question" && hasRole("admin", "supervisor")) loadRules();
    $("#reportDialog").close();
    toast(reportId ? "Report atualizado." : "Report registrado e encaminhado para análise.");
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("hidden");
  } finally {
    button.disabled = false;
  }
}

function openReportReview(item) {
  if (!item || !hasRole("admin", "supervisor")) return;
  $("#reportReviewForm").reset();
  $("#reportReviewError").classList.add("hidden");
  $("#reportReviewId").value = item.id;
  $("#reportReviewTitle").textContent = item.title;
  $("#reportReviewStatus").value = item.status;
  $("#reportReviewPriority").value = item.priority;
  $("#reportAssignee").innerHTML = '<option value="">Sem responsável</option>' + reportAssignees.map(user => `<option value="${user.id}">${escapeHtml(user.display_name)}</option>`).join("");
  $("#reportAssignee").value = item.assignee_user_id ? String(item.assignee_user_id) : "";
  $("#reportRuleAction").value = item.rule_action || "keep";
  $("#reportRuleAction").disabled = !["Resolvido", "Descartado"].includes(item.status);
  $("#reportResolution").value = item.resolution || "";
  $("#reportReviewContext").innerHTML = `<strong>${escapeHtml(item.type_label)} · reportado por ${escapeHtml(item.reporter_name)}</strong><small>${escapeHtml(item.description)}</small>${item.reference ? `<small>Referência: ${escapeHtml(item.reference)}</small>` : ""}`;
  $("#reportReviewDialog").showModal();
}

async function saveReportReview(event) {
  event.preventDefault();
  const id = Number($("#reportReviewId").value);
  const button = $("#saveReportReview");
  const errorBox = $("#reportReviewError");
  errorBox.classList.add("hidden");
  button.disabled = true;
  try {
    const saved = await reportRequest(`/${id}`, {
      method: "PUT",
      body: JSON.stringify({
        status: $("#reportReviewStatus").value,
        priority: $("#reportReviewPriority").value,
        resolution: $("#reportResolution").value,
        assignee_user_id: $("#reportAssignee").value,
        rule_action: $("#reportRuleAction").value,
      }),
    });
    const index = reports.findIndex(item => item.id === id);
    if (index >= 0) reports[index] = saved;
    renderReports();
    $("#reportReviewDialog").close();
    toast("Tratativa do report atualizada.");
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("hidden");
  } finally {
    button.disabled = false;
  }
}

function formatReportFileSize(size) {
  return size >= 1024 * 1024 ? `${(size / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(size / 1024))} KB`;
}

function openReportDetails(item) {
  if (!item) return;
  $("#reportDetailId").value = item.id;
  $("#reportDetailTitle").textContent = item.title;
  $("#reportDetailError").classList.add("hidden");
  $("#reportComment").value = "";
  $("#reportDetailFile").value = "";
  const canCollaborate = hasRole("admin", "supervisor") || (hasRole("operator") && item.reporter_username === currentUser.username);
  document.querySelector(".report-collaboration").classList.toggle("hidden", !canCollaborate);
  $("#addReportComment").classList.toggle("hidden", !canCollaborate);
  $("#addReportAttachment").classList.toggle("hidden", !canCollaborate);
  const comments = item.comments.length ? item.comments.map(comment => `<div class="report-history-item"><strong>${escapeHtml(comment.author_name)}</strong><small>${formatInstructorDate(comment.created_at)}</small><p>${escapeHtml(comment.body)}</p></div>`).join("") : '<p class="report-empty-detail">Nenhum comentário.</p>';
  const attachments = item.attachments.length ? item.attachments.map(file => `<div class="report-attachment"><a href="/api/report-attachments/${file.id}" target="_blank" rel="noopener">${escapeHtml(file.filename)}</a><small>${formatReportFileSize(file.size_bytes)} · ${escapeHtml(file.uploaded_by_name)}</small>${canCollaborate ? `<button type="button" data-report-attachment-delete="${file.id}">Excluir</button>` : ""}</div>`).join("") : '<p class="report-empty-detail">Nenhum anexo.</p>';
  const events = item.events.length ? item.events.map(event => `<div class="report-event"><span>${escapeHtml(event.action)}</span><small>${escapeHtml(event.actor_name)} · ${formatInstructorDate(event.created_at)}</small></div>`).join("") : '<p class="report-empty-detail">Sem eventos.</p>';
  $("#reportDetailContent").innerHTML = `<div class="report-detail-summary"><p>${escapeHtml(item.description)}</p>${item.reference ? `<small>Referência: ${escapeHtml(item.reference)}</small>` : ""}${item.assignee_name ? `<small>Responsável: ${escapeHtml(item.assignee_name)}</small>` : ""}${reportRuleBadge(item)}</div><section><h3>Comentários</h3>${comments}</section><section><h3>Anexos</h3>${attachments}</section><section><h3>Auditoria</h3>${events}</section>`;
  document.querySelectorAll("[data-report-attachment-delete]").forEach(button => button.addEventListener("click", () => removeReportAttachment(Number(button.dataset.reportAttachmentDelete))));
  $("#reportDetailDialog").showModal();
}

async function addCurrentReportComment() {
  const id = Number($("#reportDetailId").value);
  try {
    await reportRequest(`/${id}/comments`, { method: "POST", body: JSON.stringify({ body: $("#reportComment").value }) });
    await loadReports();
    openReportDetails(reports.find(item => item.id === id));
    toast("Comentário adicionado.");
  } catch (error) { setDialogMessage("#reportDetailError", error.message); }
}

async function addCurrentReportAttachment() {
  const id = Number($("#reportDetailId").value);
  const file = $("#reportDetailFile").files[0];
  if (!file) { setDialogMessage("#reportDetailError", "Selecione um arquivo."); return; }
  try {
    await uploadReportFiles(id, [file]);
    await loadReports();
    openReportDetails(reports.find(item => item.id === id));
    toast("Anexo adicionado.");
  } catch (error) { setDialogMessage("#reportDetailError", error.message); }
}

async function removeReportAttachment(id) {
  if (!window.confirm("Excluir este anexo do report?")) return;
  const reportId = Number($("#reportDetailId").value);
  try {
    await apiFetch(`${window.location.origin}/api/report-attachments/${id}`, { method: "DELETE" }).then(async response => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Não foi possível excluir o anexo.");
    });
    await loadReports();
    openReportDetails(reports.find(item => item.id === reportId));
  } catch (error) { setDialogMessage("#reportDetailError", error.message); }
}

async function ruleRequest(path = "", options = {}) {
  const response = await apiFetch(`${window.location.origin}/api/${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Não foi possível acessar a gestão de regras.");
  return data;
}

function sourceKindLabel(value) {
  return {
    external_grounded: "Pesquisa oficial externa",
    unanswered: "Sem resposta conclusiva",
    conflict: "Conflito entre fontes",
    operator_report: "Indicação do operador",
    local_document: "Catálogo documental local",
  }[value] || value;
}

function renderRules() {
  const list = $("#ruleReviewList");
  const search = normalizeText($("#ruleSearch").value);
  const dateFrom = $("#ruleDateFrom").value;
  const dateTo = $("#ruleDateTo").value;
  const minOccurrences = Number($("#ruleMinOccurrences").value || 1);
  const openCount = unreviewedRules.length + pendingApprovalRules.length;
  $("#unreviewedRuleCount").textContent = unreviewedRules.length;
  $("#pendingApprovalRuleCount").textContent = pendingApprovalRules.length;
  $("#approvedRuleCount").textContent = approvedRules.length;
  const visibleOpen = knowledgeGapItems.filter(item => {
    const lastDate = String(item.last_asked_at || "").slice(0, 10);
    const haystack = normalizeText([
      item.question, item.proposed_answer, item.source_reference, item.authority,
      item.created_by_name, item.created_by_username,
    ].join(" "));
    return (!search || haystack.includes(search))
      && (!dateFrom || lastDate >= dateFrom)
      && (!dateTo || lastDate <= dateTo)
      && Number(item.occurrence_count || 0) >= minOccurrences;
  });
  $("#recurringRuleCount").textContent = new Set(visibleOpen
    .filter(item => item.group_occurrence_count > 1)
    .map(item => item.similar_group_id)).size;
  $("#ruleOccurrenceCount").textContent = visibleOpen.reduce(
    (total, item) => total + Number(item.occurrence_count || 0), 0
  );
  $("#ruleCandidateNavCount").textContent = openCount;
  $("#ruleCandidateNavCount").classList.toggle("hidden", !openCount);
  $("#unreviewedRulesTab").classList.toggle("active", activeRulesTab === "unreviewed");
  $("#pendingApprovalRulesTab").classList.toggle("active", activeRulesTab === "pending_approval");
  $("#approvedRulesTab").classList.toggle("active", activeRulesTab === "approved");
  const source = activeRulesTab === "unreviewed"
    ? unreviewedRules
    : activeRulesTab === "pending_approval" ? pendingApprovalRules : approvedRules;
  const filtered = source.filter(item => normalizeText([
    item.question, item.proposed_answer, item.approved_rule_text, item.rule_code,
    item.source_reference, item.authority, item.created_by_name, item.created_by_username,
  ].join(" ")).includes(search)).filter(item => activeRulesTab === "approved" || (
    (!dateFrom || String(item.last_asked_at || "").slice(0, 10) >= dateFrom)
    && (!dateTo || String(item.last_asked_at || "").slice(0, 10) <= dateTo)
    && Number(item.occurrence_count || 0) >= minOccurrences
  ));
  if (!filtered.length) {
    const emptyMessages = {
      unreviewed: "Nenhuma regra aguardando a primeira revisão.",
      pending_approval: "Nenhuma regra pendente de aprovação.",
      approved: "Nenhuma regra aprovada encontrada.",
    };
    list.innerHTML = `<div class="table-message">${emptyMessages[activeRulesTab]}</div>`;
    return;
  }
  if (activeRulesTab !== "approved") {
    const isUnreviewed = activeRulesTab === "unreviewed";
    list.innerHTML = filtered.map(item => `
      <article class="rule-review-card ${isUnreviewed ? "unreviewed" : "pending-approval"}">
        <div class="rule-review-head">
          <div><span class="rule-kind ${isUnreviewed ? "unreviewed" : "pending-approval"}">${isUnreviewed ? "NÃO REVISADA" : "PENDENTE DE APROVAÇÃO"}</span><strong>${escapeHtml(item.document_id || `#${item.id}`)} · ${escapeHtml(item.question)}</strong></div>
          <span class="rule-occurrences">${item.occurrence_count} ocorrência${item.occurrence_count === 1 ? "" : "s"}</span>
        </div>
        ${item.similar_group_size > 1 ? `<div class="similar-gap-note"><strong>${item.similar_group_size} perguntas semelhantes</strong><span>${item.group_occurrence_count} consultas no grupo</span></div>` : ""}
        <p>${escapeHtml(item.proposed_answer || "Nenhuma proposta de resposta foi localizada.")}</p>
        <div class="rule-meta"><span>Origem: ${escapeHtml(sourceKindLabel(item.source_kind))}</span><span>Confiança: ${escapeHtml(item.confidence)}</span><span>Primeira: ${formatInstructorDate(item.first_asked_at)}</span><span>Última: ${formatInstructorDate(item.last_asked_at)}</span><span>${item.sources.length} fonte(s)</span>${item.created_by_name || item.created_by_username ? `<span>Registrada por: ${escapeHtml(item.created_by_name || item.created_by_username)}</span>` : ""}${item.document_path ? `<span>Documento: ${escapeHtml(item.document_path)}</span>` : ""}${!isUnreviewed && item.reviewed_by_name ? `<span>Revisada por: ${escapeHtml(item.reviewed_by_name)}</span>` : ""}</div>
        ${!isUnreviewed && item.review_note ? `<div class="rule-review-note"><strong>ÚLTIMA ANÁLISE</strong>${escapeHtml(item.review_note)}</div>` : ""}
        ${item.sources.length ? `<div class="rule-source-links">${item.sources.slice(0, 3).map(sourceItem => sourceItem.url ? `<a href="${escapeHtml(sourceItem.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(sourceItem.label || sourceItem.url)} ↗</a>` : "").join("")}</div>` : ""}
        <div class="rule-card-actions"><button class="primary-button compact-button" type="button" data-rule-review="${item.id}">${isUnreviewed ? "Iniciar revisão" : "Continuar análise"}</button><button class="secondary-button compact-button" type="button" data-rule-reprocess="${item.id}">Reprocessar</button></div>
      </article>`).join("");
    list.querySelectorAll("[data-rule-review]").forEach(button => button.addEventListener("click", () => openRuleReview(Number(button.dataset.ruleReview))));
    list.querySelectorAll("[data-rule-reprocess]").forEach(button => button.addEventListener("click", () => reprocessRule(Number(button.dataset.ruleReprocess), button)));
    return;
  }
  list.innerHTML = filtered.map(item => `
    <article class="rule-review-card approved">
      <div class="rule-review-head"><div><span class="rule-kind approved">APROVADA</span><strong>${escapeHtml(item.rule_code || "Regra aprovada")}</strong></div><span>${escapeHtml(item.authority || "Base SAFE aprovada")}</span></div>
      <p>${escapeHtml(item.approved_rule_text || "")}</p>
      <div class="rule-meta"><span>${escapeHtml(item.source_reference || "Referência na base aprovada")}</span>${item.scope ? `<span>Escopo: ${escapeHtml(item.scope)}</span>` : ""}</div>
      ${item.source_url ? `<div class="rule-source-links"><a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener noreferrer">Abrir fonte oficial ↗</a></div>` : ""}
      ${item.origin === "reviewed_candidate" ? `<button class="primary-button compact-button" type="button" data-rule-review="${item.id}">Revisar regra aprovada</button>` : ""}
    </article>`).join("");
  list.querySelectorAll("[data-rule-review]").forEach(button => button.addEventListener("click", () => openRuleReview(Number(button.dataset.ruleReview))));
}

async function loadRules() {
  try {
    const [gaps, approved] = await Promise.all([
      ruleRequest("knowledge-gaps?status=open"),
      ruleRequest("approved-rules"),
    ]);
    knowledgeGapItems = gaps.items;
    unreviewedRules = gaps.items.filter(item => item.status === "unreviewed");
    pendingApprovalRules = gaps.items.filter(item => item.status === "pending_approval");
    approvedRules = approved.items;
    rulesLoaded = true;
    renderRules();
  } catch (error) {
    $("#ruleReviewList").innerHTML = `<div class="table-message">${escapeHtml(error.message)}</div>`;
    toast(error.message);
  }
}

async function reprocessRule(id, button) {
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "Reprocessando…";
  try {
    await ruleRequest(`rule-candidates/${id}/reprocess`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    await loadRules();
    toast("Lacuna reprocessada sem alterar sua contagem de ocorrências.");
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function nextRuleCode() {
  const numbers = approvedRules.map(item => /^RG-(\d{3})$/.exec(item.rule_code || ""))
    .filter(Boolean).map(match => Number(match[1]));
  return `RG-${String((numbers.length ? Math.max(...numbers) : 0) + 1).padStart(3, "0")}`;
}

function openRuleReview(id) {
  const item = unreviewedRules.find(candidate => candidate.id === id)
    || pendingApprovalRules.find(candidate => candidate.id === id)
    || approvedRules.find(rule => rule.origin === "reviewed_candidate" && rule.id === id);
  if (!item) return;
  $("#ruleReviewForm").reset();
  $("#ruleReviewError").classList.add("hidden");
  $("#ruleReviewId").value = item.id;
  $("#ruleReviewTitle").textContent = item.status === "unreviewed"
    ? `Primeira revisão da proposta ${item.document_id || `#${item.id}`}`
    : `Analisar proposta ${item.document_id || `#${item.id}`}`;
  $("#ruleReviewContext").innerHTML = `<strong>${escapeHtml(item.question)}</strong><p>${escapeHtml(item.proposed_answer || "Sem proposta de resposta.")}</p><small>${escapeHtml(item.status_label || sourceKindLabel(item.source_kind))} · ${item.occurrence_count} ocorrência(s)${item.document_path ? ` · ${escapeHtml(item.document_path)}` : ""}</small>`;
  $("#ruleReviewStatus").value = item.status === "unreviewed" ? "pending_approval" : item.status;
  $("#ruleCode").value = item.rule_code || nextRuleCode();
  $("#approvedRuleText").value = item.approved_rule_text || item.proposed_answer || "";
  $("#ruleAuthority").value = item.authority || "";
  $("#ruleSourceReference").value = item.source_reference || item.sources[0]?.label || "";
  $("#ruleSourceUrl").value = item.source_url || item.sources[0]?.url || "";
  $("#ruleScope").value = item.scope || "";
  $("#ruleEffectiveFrom").value = item.effective_from || "";
  $("#ruleEffectiveUntil").value = item.effective_until || "";
  $("#ruleSupersedes").value = item.supersedes || "";
  $("#ruleReviewNote").value = item.review_note || "";
  $("#ruleReviewDialog").showModal();
}

async function saveRuleReview(event) {
  event.preventDefault();
  const id = Number($("#ruleReviewId").value);
  const button = $("#saveRuleReview");
  const errorBox = $("#ruleReviewError");
  errorBox.classList.add("hidden");
  button.disabled = true;
  try {
    await ruleRequest(`rule-candidates/${id}`, {
      method: "PUT",
      body: JSON.stringify({
        status: $("#ruleReviewStatus").value,
        rule_code: $("#ruleCode").value,
        approved_rule_text: $("#approvedRuleText").value,
        authority: $("#ruleAuthority").value,
        source_reference: $("#ruleSourceReference").value,
        source_url: $("#ruleSourceUrl").value,
        scope: $("#ruleScope").value,
        effective_from: $("#ruleEffectiveFrom").value,
        effective_until: $("#ruleEffectiveUntil").value,
        supersedes: $("#ruleSupersedes").value,
        review_note: $("#ruleReviewNote").value,
      }),
    });
    $("#ruleReviewDialog").close();
    await loadRules();
    toast("Decisão registrada. A trilha de auditoria foi atualizada.");
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("hidden");
  } finally {
    button.disabled = false;
  }
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
    const data = await response.json();
    status.dataset.state = "online";
    $("#systemStatusText").textContent = "Operacional";
    const updatedAt = data.updated_at ? new Date(data.updated_at) : null;
    const validDate = updatedAt && !Number.isNaN(updatedAt.getTime());
    $("#portalUpdatedAt").textContent = validDate
      ? new Intl.DateTimeFormat("pt-BR", {
        day: "2-digit", month: "2-digit", year: "numeric",
        hour: "2-digit", minute: "2-digit", timeZone: "America/Sao_Paulo",
      }).format(updatedAt).replace(",", " ·")
      : "Não informada";
    $("#portalUpdate").title = validDate
      ? `Última atualização publicada: ${updatedAt.toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" })}`
      : "Data da última atualização não informada";
  } catch {
    status.dataset.state = "offline";
    $("#systemStatusText").textContent = "Indisponível";
    $("#portalUpdatedAt").textContent = "Não disponível";
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
  $("#ruleManagementNav").classList.toggle("hidden", !hasRole("admin", "supervisor"));
  $("#reportsNavItem").classList.toggle("hidden", user.role === "viewer");
  $("#addAircraft").classList.toggle("hidden", !hasRole("admin", "supervisor"));
  $("#addHandover").classList.toggle("hidden", user.role === "viewer");
  $("#addReport").classList.toggle("hidden", user.role === "viewer");
  $("#reportAnswerIssue").classList.toggle("hidden", user.role === "viewer");
  $("#accountDialogName").textContent = user.display_name;
  $("#accountDialogRole").textContent = `${user.role_label} · ${user.username}`;
  $("#closeAccount").classList.toggle("hidden", user.must_change_password);
  if (user.must_change_password) {
    setDialogMessage(
      "#accountFormError",
      "Esta é uma senha temporária. Informe-a como senha atual e escolha a nova senha para liberar o portal.",
      "notice",
    );
    $("#accountDialog").showModal();
  } else {
    setDialogMessage("#accountFormError");
    bootstrapPortal();
  }
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
    renderAircraft(); renderHandovers(); renderReports();
    if (hasRole("admin", "supervisor") && rulesLoaded) renderRules();
    return;
  }
  portalBootstrapped = true;
  loadSearchHistory();
  loadHandovers();
  loadAircraft();
  loadPortalActivity();
  if (!hasRole("viewer")) loadReports();
  if (hasRole("admin", "supervisor")) loadRules();
  updateShiftStatus();
  updateSystemStatus();
  setInterval(updateShiftStatus, 30_000);
  setInterval(updateSystemStatus, 60_000);
  setInterval(() => {
    if (!document.hidden) {
      pingPortalActivity();
      loadPortalActivity();
    }
  }, 30_000);
  applyInitialRoute();
  pingPortalActivity();
}

function applyInitialRoute() {
  const params = new URLSearchParams(window.location.search);
  const initialQuestion = params.get("q");
  const initialView = params.get("view");
  if (initialQuestion) { input.value = initialQuestion; searchBox.classList.add("has-value"); search(initialQuestion); }
  if (["aeronaves", "passagem", "reports", "gestao-regras", "usuarios", "atividade"].includes(initialView)) {
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

function activityInitials(name) {
  return String(name || "U").split(/\s+/).filter(Boolean).slice(0, 2).map(value => value[0]).join("").toUpperCase();
}

function activityRelativeTime(value) {
  if (!value) return "Nunca";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Não informado";
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "Agora";
  if (seconds < 3600) return `Há ${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `Há ${Math.floor(seconds / 3600)} h`;
  return formatInstructorDate(value);
}

function renderPortalActivity(data) {
  portalActivity = data.items || [];
  activityLoaded = true;
  $("#activityOnlineCount").textContent = data.online_count || 0;
  $("#activityRecentCount").textContent = data.recent_count || 0;
  $("#activityDayCount").textContent = data.accessed_24h_count || 0;
  $("#activityUserCount").textContent = data.active_user_count || 0;
  $("#activityNavCount").textContent = data.online_count > 99 ? "99+" : String(data.online_count || 0);
  $("#activityRows").innerHTML = portalActivity.length ? portalActivity.map(item => `<tr>
    <td><div class="activity-user"><span class="activity-avatar">${escapeHtml(activityInitials(item.display_name))}</span><div><strong>${escapeHtml(item.display_name)}</strong><small>@${escapeHtml(item.username)}</small></div></div></td>
    <td><span class="user-role-badge">${escapeHtml(item.role_label)}</span></td>
    <td><span class="presence-badge ${item.online ? "online" : ""}">${item.online ? "Online agora" : "Offline"}</span></td>
    <td title="${escapeHtml(item.last_activity_at || "")}">${escapeHtml(activityRelativeTime(item.last_activity_at))}</td>
    <td><span class="activity-area">${escapeHtml(item.last_activity_area || "Sem atividade registrada")}</span></td>
    <td title="${escapeHtml(item.last_login_at || "")}">${escapeHtml(activityRelativeTime(item.last_login_at))}</td>
  </tr>`).join("") : `<tr><td colspan="6" class="table-message">Nenhum usuário ativo cadastrado.</td></tr>`;
  $("#activityUpdatedAt").textContent = `Atualizado em ${formatInstructorDate(data.generated_at)} · atualização automática a cada 30 segundos.`;
}

async function loadPortalActivity(showError = false) {
  try {
    const response = await apiFetch(`${window.location.origin}/api/activity`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Não foi possível carregar a atividade.");
    renderPortalActivity(data);
  } catch (error) {
    if (showError) {
      $("#activityRows").innerHTML = `<tr><td colspan="6" class="table-message">${escapeHtml(error.message)}</td></tr>`;
      toast(error.message);
    }
  }
}

async function pingPortalActivity(area = currentActivityArea) {
  try {
    await apiFetch(`${window.location.origin}/api/activity/ping`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ area }),
    });
  } catch (error) {
    console.info("Registro de atividade temporariamente indisponível.", error.message);
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
  if (key === "aeronaves") {
    showView(aircraftView, "Aeronaves");
    if (!aircraftLoaded) loadAircraft();
    return;
  }
  if (key === "atividade") {
    showView(activityView, "Atividade do portal");
    loadPortalActivity(true);
    return;
  }
  if (key === "passagem") {
    showView(handoverView, "Passagem de turno");
    if (!handoversLoaded) loadHandovers();
    return;
  }
  if (key === "reports") {
    if (hasRole("viewer")) { toast("O perfil de consulta não possui acesso aos reports."); return; }
    showView(reportsView, "Reports");
    if (!reportsLoaded) loadReports();
    return;
  }
  if (key === "gestao-regras") {
    if (!hasRole("admin", "supervisor")) { toast("Somente Supervisor ou Administrador pode revisar regras."); return; }
    showView(ruleManagementView, "Gestão de regras");
    if (!rulesLoaded) loadRules();
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
$("#newSearchButton").addEventListener("click", startNewSearch);
$("#moduleBack").addEventListener("click", () => showView(homeView, "Regras e procedimentos"));
$("#returnHome").addEventListener("click", () => showView(homeView, "Regras e procedimentos"));
$("#menuButton").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
$("#sourceButton").addEventListener("click", () => {
  if (!currentSourceUrl) { toast("A fonte está registrada na base interna."); return; }
  window.open(currentSourceUrl, "_blank", "noopener,noreferrer");
});
$("#addAircraft").addEventListener("click", () => openAircraftDialog());
$("#aircraftSearch").addEventListener("input", renderAircraft);
$("#aircraftBaseFilter").addEventListener("change", renderAircraft);
$("#aircraftFleetFilter").addEventListener("change", renderAircraft);
$("#aircraftStatusFilter").addEventListener("change", renderAircraft);
$("#aircraftForm").addEventListener("submit", saveAircraft);
$("#deleteAircraft").addEventListener("click", removeAircraft);
$("#refreshActivity").addEventListener("click", () => loadPortalActivity(true));
$("#addHandover").addEventListener("click", () => openHandoverDialog());
$("#handoverShiftFilter").addEventListener("change", renderHandovers);
$("#handoverForm").addEventListener("submit", saveHandover);
$("#deleteHandover").addEventListener("click", removeHandover);
$("#addReport").addEventListener("click", () => openReportDialog());
$("#reportTypeFilter").addEventListener("change", renderReports);
$("#reportStatusFilter").addEventListener("change", renderReports);
$("#reportPriorityFilter").addEventListener("change", renderReports);
$("#reportAuthorFilter").addEventListener("change", renderReports);
$("#reportDateFrom").addEventListener("change", renderReports);
$("#reportDateTo").addEventListener("change", renderReports);
$("#reportSearch").addEventListener("input", renderReports);
$("#reportForm").addEventListener("submit", saveReport);
$("#reportReviewForm").addEventListener("submit", saveReportReview);
$("#reportReviewStatus").addEventListener("change", () => {
  const status = $("#reportReviewStatus").value;
  $("#reportRuleAction").value = status === "Resolvido" ? "pending_approval" : status === "Descartado" ? "no_rule" : "keep";
  $("#reportRuleAction").disabled = !["Resolvido", "Descartado"].includes(status);
});
$("#addReportComment").addEventListener("click", addCurrentReportComment);
$("#addReportAttachment").addEventListener("click", addCurrentReportAttachment);
$("#unreviewedRulesTab").addEventListener("click", () => { activeRulesTab = "unreviewed"; renderRules(); });
$("#pendingApprovalRulesTab").addEventListener("click", () => { activeRulesTab = "pending_approval"; renderRules(); });
$("#approvedRulesTab").addEventListener("click", () => { activeRulesTab = "approved"; renderRules(); });
$("#ruleSearch").addEventListener("input", renderRules);
$("#ruleDateFrom").addEventListener("change", renderRules);
$("#ruleDateTo").addEventListener("change", renderRules);
$("#ruleMinOccurrences").addEventListener("change", renderRules);
$("#exportKnowledgeGaps").addEventListener("click", () => {
  const params = new URLSearchParams({ status: "open" });
  if ($("#ruleSearch").value) params.set("search", $("#ruleSearch").value);
  if ($("#ruleDateFrom").value) params.set("from", $("#ruleDateFrom").value);
  if ($("#ruleDateTo").value) params.set("to", $("#ruleDateTo").value);
  params.set("min_occurrences", $("#ruleMinOccurrences").value || "1");
  window.location.assign(`${window.location.origin}/api/knowledge-gaps/export.csv?${params}`);
});
$("#printKnowledgeGaps").addEventListener("click", () => window.print());
$("#ruleReviewForm").addEventListener("submit", saveRuleReview);
$("#reportAnswerIssue").addEventListener("click", () => {
  const question = $("#answerQuestion").textContent.trim();
  const source = $("#sourceTitle").textContent.trim();
  const sourceDetail = $("#sourceDetail").textContent.trim();
  openReportDialog({
    report_type: "discrepancy",
    priority: "Alta",
    title: `Revisar resposta: ${question}`.slice(0, 160),
    reference: [`Pergunta: ${question}`, `Fonte exibida: ${source}`, sourceDetail].filter(Boolean).join("\n"),
  });
});
$("#shiftStatusCard").addEventListener("click", () => {
  document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === "passagem"));
  openModule("passagem");
});
$("#notificationButton").addEventListener("click", () => {
  const target = Number($("#notificationButton").dataset.criticalReports || 0) > 0 && !hasRole("viewer") ? "reports" : "passagem";
  document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === target));
  openModule(target);
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
$("#accountButton").addEventListener("click", () => {
  setDialogMessage("#accountFormError");
  $("#accountDialog").showModal();
});
$("#closeAccount").addEventListener("click", () => {
  if (!currentUser?.must_change_password) $("#accountDialog").close();
});
$("#accountDialog").addEventListener("cancel", event => {
  if (currentUser?.must_change_password) event.preventDefault();
});
$("#changePasswordForm").addEventListener("submit", async event => {
  event.preventDefault();
  const button = $("#saveOwnPassword");
  setDialogMessage("#accountFormError");
  button.disabled = true;
  try {
    const response = await apiFetch(`${window.location.origin}/api/auth/change-password`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: $("#currentPassword").value, new_password: $("#newPassword").value }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Não foi possível alterar a senha.");
    currentUser.must_change_password = false;
    $("#closeAccount").classList.remove("hidden");
    event.currentTarget.reset(); $("#accountDialog").close(); bootstrapPortal(); toast("Senha alterada com sucesso.");
  } catch (error) {
    setDialogMessage("#accountFormError", error.message);
  } finally {
    button.disabled = false;
  }
});
$("#logoutButton").addEventListener("click", async () => {
  try { await apiFetch(`${window.location.origin}/api/auth/logout`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); } catch {}
  currentUser = null; csrfToken = ""; $("#accountDialog").close(); showAuthGate(false);
});
function toast(message) { const element = $("#toast"); element.textContent = message; element.classList.add("show"); setTimeout(() => element.classList.remove("show"), 2800); }
initializeAuth();
