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
const input = $("#searchInput");
const searchBox = $("#searchForm");
const searchResults = $("#searchResults");
let suggestionItems = [];
let activeSuggestion = -1;
let history = JSON.parse(localStorage.getItem("safe-cco-history") || "[]");

function showView(view, name) {
  [homeView, answerView, moduleView].forEach(item => item.classList.add("hidden"));
  view.classList.remove("hidden");
  $("#pageName").textContent = name;
  window.scrollTo({ top: 0, behavior: "smooth" });
  $("#sidebar").classList.remove("open");
}

function renderHistory() {
  const box = $("#recentList");
  if (!history.length) { box.innerHTML = `<div class="empty-recent">Suas consultas aparecerão aqui.</div>`; return; }
  box.innerHTML = history.slice(0, 3).map((item, index) => `<button class="recent-item" data-history="${index}" style="width:100%;border-left:0;border-right:0;border-bottom:0;background:none;text-align:left;cursor:pointer"><span class="recent-type">⌕</span><span class="recent-text"><strong>${item.question}</strong><small>${item.time} · Regra operacional</small></span><span>→</span></button>`).join("");
  box.querySelectorAll("[data-history]").forEach(button => button.addEventListener("click", () => search(history[button.dataset.history].question)));
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
  return [...graphIndex.claims.map(item => ({ ...item, kind: "Regra confirmada" })), ...graphIndex.documents.map(item => ({ ...item, kind: "Documento relacionado" }))]
    .map(item => ({ ...item, score: scoreRecord(item, tokens) }))
    .filter(item => item.score >= Math.max(4, tokens.length * 2))
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
  const rows = results.map(item => `<div class="answer-highlight"><strong>${item.label}</strong><br><small>${item.kind}${item.code ? ` · ${item.code}` : ""}${item.location ? ` · ${item.location}` : ""}</small></div>`).join("");
  return {
    question: query,
    answer: `<p>Encontrei <strong>${results.length} resultado(s) relacionado(s)</strong> no índice atual do grafo. Os itens abaixo são apresentados com rastreabilidade; quando não formarem uma resposta conclusiva, valide a decisão na fonte.</p>${rows}`,
    source: primary.code || primary.label,
    detail: `${primary.source || "Grafo de conhecimento SAFE"}${primary.location ? ` · ${primary.location}` : ""}`,
    relations: results.slice(0, 3).map(item => [item.kind.toUpperCase(), item.label, item.code || item.source || "Grafo SAFE"])
  };
}

function showAnswer(item, originalQuestion) {
  $("#answerQuestion").textContent = originalQuestion || item.question;
  $("#answerBody").innerHTML = item.answer;
  $("#sourceTitle").textContent = item.source;
  $("#sourceDetail").textContent = item.detail;
  $("#relationList").innerHTML = item.relations.map(r => `<div class="relation"><small>${r[0]}</small><strong>${r[1]}</strong><span>${r[2]}</span></div>`).join("");
  history = [{ question: item.question, time: "Agora" }, ...history.filter(h => h.question !== item.question)].slice(0, 5);
  localStorage.setItem("safe-cco-history", JSON.stringify(history));
  renderHistory();
  showView(answerView, "Resposta");
}

function search(query) {
  if (!query.trim()) { input.focus(); return; }
  closeSearchSuggestions();
  const answer = findAnswer(query);
  if (answer) showAnswer(answer, query);
  else {
    const results = findGraphResults(query);
    if (results.length) showAnswer(graphResultAnswer(query, results), query);
    else showAnswer({ question: query, answer: `<p>Não encontrei uma regra confirmada para esta pergunta no índice atual.</p><div class="answer-highlight"><strong>Não tome uma decisão apenas com esta resposta.</strong> Consulte a documentação oficial ou encaminhe a dúvida para revisão.</div>`, source: "Nenhuma fonte confirmada localizada", detail: "Consulta pendente de ampliação da base", relations: [["STATUS", "Conhecimento ainda não indexado", "Requer análise documental"], ["PRÓXIMA AÇÃO", "Consultar documentação oficial", "Validação humana necessária"]] }, query);
  }
}

function openModule(key) {
  if (key === "inicio") { showView(homeView, "Visão geral"); return; }
  if (key === "regras" || key === "consulta") { showView(homeView, "Visão geral"); setTimeout(() => input.focus(), 200); return; }
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
document.querySelectorAll("[data-question]").forEach(button => button.addEventListener("click", () => { input.value = button.dataset.question; search(input.value); }));
document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => { document.querySelectorAll(".nav-item").forEach(item => item.classList.remove("active")); button.classList.add("active"); openModule(button.dataset.view); }));
document.querySelectorAll(".module-card").forEach(card => card.addEventListener("click", () => openModule(card.dataset.target)));
$("#backButton").addEventListener("click", () => showView(homeView, "Visão geral"));
$("#moduleBack").addEventListener("click", () => showView(homeView, "Visão geral"));
$("#returnHome").addEventListener("click", () => showView(homeView, "Visão geral"));
$("#menuButton").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
$("#sourceButton").addEventListener("click", () => toast("A abertura do documento original será conectada na próxima integração."));
$("#customizeButton").addEventListener("click", () => toast("A personalização de atalhos será habilitada em uma próxima etapa."));
function toast(message) { const element = $("#toast"); element.textContent = message; element.classList.add("show"); setTimeout(() => element.classList.remove("show"), 2800); }
renderHistory();
$("#ruleCount").textContent = graphIndex.meta.confirmedClaims ?? knowledge.length;
$("#indexStatus").textContent = graphIndex.meta.generatedAt ? "Índice sincronizado" : "Modo demonstrativo";
