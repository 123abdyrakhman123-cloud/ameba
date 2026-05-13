const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
if (tg) { tg.ready(); tg.expand(); }

const ADMIN_IDS = [1427715527, 905937261, 8113642902, 771714551, 1347147831, 751240103, 1238729309, 6586083917, 921010964, 1333298810, 942664226, 1239722079];

const SUBJECT_NAMES = {
  histology: "Гистология", microbiology: "Микробиология", biochemistry: "Биохимия",
  pharmacology: "Фармакология", therapy3: "Терапия 3", pediatrics3: "Педиатрия 3",
  surgery3: "Хирургия 3", hygiene: "Гигиена", pathophysiology: "Патфиз",
  obstetrics: "АиГ", therapy4: "Терапия 4", dermatology: "Дерматология",
  lor: "ЛОР", neurology: "Неврология", mmp: "ВМП", ophthalmology: "Офтальмология",
  surgery5: "Хирургия 5", psychiatry: "Психиатрия", infections: "Инфекционные болезни",
  therapy5: "Терапия 5", pediatrics5: "Педиатрия 5",
};

let allQuestions = [];
let filteredQuestions = [];
let searchTimer = null;
const initData = (tg && tg.initData) ? tg.initData : "";
let sessionToken = localStorage.getItem("admin_token") || "";

function getAuth() {
  return sessionToken || initData;
}

// ==================== HELPERS ====================

function showScreen(id) {
  document.querySelectorAll(".screen").forEach(s => s.classList.add("hidden"));
  document.getElementById(id).classList.remove("hidden");
}

function showToast(msg, type) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast" + (type ? " " + type : "");
  t.classList.remove("hidden");
  setTimeout(() => t.classList.add("hidden"), 2500);
}

function escHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ==================== AUTH ====================

async function init() {
  const auth = getAuth();
  if (!auth) {
    showScreen("screen-password");
    return;
  }
  try {
    const resp = await fetch("/api/admin/check", {
      headers: { Authorization: auth }
    });
    const data = await resp.json();
    if (data.is_admin) {
      showScreen("screen-list");
      await loadSubjects();
      await loadQuestions();
    } else {
      // initData не прошёл — покажем пароль
      sessionToken = "";
      localStorage.removeItem("admin_token");
      showScreen("screen-password");
    }
  } catch (e) {
    showScreen("screen-password");
  }
}

// ==================== PASSWORD LOGIN ====================

document.getElementById("btn-password-login").addEventListener("click", async () => {
  const pwd = document.getElementById("input-password").value.trim();
  if (!pwd) return;
  try {
    const resp = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: pwd })
    });
    const data = await resp.json();
    if (data.success) {
      sessionToken = data.token;
      localStorage.setItem("admin_token", data.token);
      showScreen("screen-list");
      await loadSubjects();
      await loadQuestions();
    } else {
      document.getElementById("password-error").textContent = "Неверный пароль";
    }
  } catch (e) {
    document.getElementById("password-error").textContent = "Ошибка соединения";
  }
});

document.getElementById("input-password").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("btn-password-login").click();
});

// ==================== LOAD ====================

async function loadSubjects() {
  const sel = document.getElementById("filter-subject");
  for (const [key, name] of Object.entries(SUBJECT_NAMES)) {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = name;
    sel.appendChild(opt);
  }
}

async function loadQuestions() {
  const listEl = document.getElementById("questions-list");
  listEl.innerHTML = '<div class="loading">Загрузка...</div>';
  try {
    const resp = await fetch("/api/admin/questions", {
      headers: { Authorization: getAuth() }
    });
    if (!resp.ok) throw new Error("err");
    const data = await resp.json();
    allQuestions = data.questions || [];
    applyFilter();
  } catch (e) {
    listEl.innerHTML = '<div class="loading">Ошибка загрузки</div>';
  }
}

function applyFilter() {
  const subject = document.getElementById("filter-subject").value;
  const search = document.getElementById("filter-search").value.trim().toLowerCase();
  filteredQuestions = allQuestions.filter(q => {
    if (subject && q.subject !== subject) return false;
    if (search && !q.question.toLowerCase().includes(search)) return false;
    return true;
  });
  renderList();
}

function renderList() {
  const listEl = document.getElementById("questions-list");
  const statsEl = document.getElementById("stats-bar");
  statsEl.textContent = `Найдено: ${filteredQuestions.length} из ${allQuestions.length}`;
  if (filteredQuestions.length === 0) {
    listEl.innerHTML = '<div class="loading">Ничего не найдено</div>';
    return;
  }
  listEl.innerHTML = "";
  for (const q of filteredQuestions) {
    const card = document.createElement("div");
    card.className = "q-card";
    const correctText = [q.option1, q.option2, q.option3, q.option4, q.option5][q.correct_option - 1] || "";
    const subjectName = SUBJECT_NAMES[q.subject] || q.subject;
    card.innerHTML = `
      <div class="q-card-header">
        <span class="q-id">#${q.id}</span>
        <span class="q-subject">${subjectName}</span>
      </div>
      <div class="q-text">${escHtml(q.question)}</div>
      <div class="q-correct">✓ ${escHtml(correctText)}</div>
    `;
    card.addEventListener("click", () => openEdit(q.id));
    listEl.appendChild(card);
  }
}

// ==================== EDIT ====================

function openEdit(id) {
  const q = allQuestions.find(x => x.id === id);
  if (!q) return;
  document.getElementById("edit-id").value = q.id;
  document.getElementById("edit-subject").value = SUBJECT_NAMES[q.subject] || q.subject;
  document.getElementById("edit-question").value = q.question || "";
  document.getElementById("edit-opt1").value = q.option1 || "";
  document.getElementById("edit-opt2").value = q.option2 || "";
  document.getElementById("edit-opt3").value = q.option3 || "";
  document.getElementById("edit-opt4").value = q.option4 || "";
  document.getElementById("edit-opt5").value = q.option5 || "";
  document.getElementById("edit-explanation").value = q.explanation || "";
  document.querySelectorAll("input[name='correct']").forEach(r => r.checked = false);
  const cr = document.getElementById(`opt-r${q.correct_option}`);
  if (cr) cr.checked = true;
  showScreen("screen-edit");
  window.scrollTo(0, 0);
}

async function saveQuestion() {
  const id = document.getElementById("edit-id").value;
  const question = document.getElementById("edit-question").value.trim();
  const option1 = document.getElementById("edit-opt1").value.trim();
  const option2 = document.getElementById("edit-opt2").value.trim();
  const option3 = document.getElementById("edit-opt3").value.trim();
  const option4 = document.getElementById("edit-opt4").value.trim();
  const option5 = document.getElementById("edit-opt5").value.trim();
  const explanation = document.getElementById("edit-explanation").value.trim();
  const correctRadio = document.querySelector("input[name='correct']:checked");
  if (!correctRadio) { showToast("Выберите правильный ответ", "error"); return; }
  if (!question) { showToast("Введите текст вопроса", "error"); return; }
  if (!option1 || !option2) { showToast("Минимум 2 варианта", "error"); return; }
  const correct_option = parseInt(correctRadio.value);
  const btn = document.getElementById("btn-save");
  btn.disabled = true; btn.textContent = "Сохранение...";
  try {
    const resp = await fetch(`/api/admin/question/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: getAuth() },
      body: JSON.stringify({ question, option1, option2, option3, option4, option5, correct_option, explanation })
    });
    const data = await resp.json();
    if (data.success) {
      const idx = allQuestions.findIndex(x => x.id === parseInt(id));
      if (idx !== -1) allQuestions[idx] = { ...allQuestions[idx], question, option1, option2, option3, option4, option5, correct_option, explanation };
      showToast("✅ Сохранено", "success");
      setTimeout(() => { showScreen("screen-list"); applyFilter(); }, 800);
    } else {
      showToast("Ошибка сохранения", "error");
    }
  } catch { showToast("Ошибка сети", "error"); }
  finally { btn.disabled = false; btn.textContent = "💾 Сохранить"; }
}

async function deleteQuestion() {
  const id = document.getElementById("edit-id").value;
  const q = allQuestions.find(x => x.id === parseInt(id));
  const preview = q ? q.question.substring(0, 60) + "..." : `#${id}`;
  if (!confirm(`Удалить вопрос?\n\n"${preview}"`)) return;
  try {
    const resp = await fetch(`/api/admin/question/${id}/delete`, {
      method: "POST", headers: { Authorization: getAuth() }
    });
    const data = await resp.json();
    if (data.success) {
      allQuestions = allQuestions.filter(x => x.id !== parseInt(id));
      showToast("🗑 Удалён", "success");
      setTimeout(() => { showScreen("screen-list"); applyFilter(); }, 800);
    } else { showToast("Ошибка удаления", "error"); }
  } catch { showToast("Ошибка сети", "error"); }
}

// ==================== TABS ====================

function switchTab(tab) {
  document.getElementById("tab-content-questions").classList.toggle("hidden", tab !== "questions");
  document.getElementById("tab-content-stats").classList.toggle("hidden", tab !== "stats");
  document.getElementById("tab-questions").classList.toggle("active", tab === "questions");
  document.getElementById("tab-stats").classList.toggle("active", tab === "stats");
  if (tab === "stats") loadStats();
}

async function loadStats() {
  const container = document.getElementById("stats-content");
  container.innerHTML = '<div class="loading">Загрузка статистики...</div>';
  try {
    const resp = await fetch("/api/admin/stats", { headers: { Authorization: getAuth() } });
    const s = await resp.json();

    const medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"];
    const topRows = s.top_subjects.map((t, i) =>
      `<div class="top-subject-row">
        <span class="top-subject-medal">${medals[i]}</span>
        <span class="top-subject-name">${SUBJECT_NAMES[t.subject] || t.subject}</span>
        <span class="top-subject-count">${t.count.toLocaleString()} отв.</span>
      </div>`
    ).join("");

    const subjectCards = s.questions_by_subject.map(q =>
      `<div class="subject-card">
        <div class="subject-card-name">${SUBJECT_NAMES[q.subject] || q.subject}</div>
        <div class="subject-card-count">${q.count}</div>
      </div>`
    ).join("");

    container.innerHTML = `
      <div class="stat-card">
        <span class="stat-icon">👥</span>
        <div class="stat-info">
          <div class="stat-value">${s.total_users.toLocaleString()}</div>
          <div class="stat-label">Пользователей</div>
        </div>
      </div>
      <div class="stat-card">
        <span class="stat-icon">💳</span>
        <div class="stat-info">
          <div class="stat-value">${s.total_purchases.toLocaleString()}</div>
          <div class="stat-label">Выдано доступов</div>
        </div>
      </div>
      <div class="stat-card">
        <span class="stat-icon">📝</span>
        <div class="stat-info">
          <div class="stat-value">${s.total_answers.toLocaleString()}</div>
          <div class="stat-label">Всего ответов</div>
        </div>
      </div>
      <div class="stat-card">
        <span class="stat-icon">🎓</span>
        <div class="stat-info">
          <div class="stat-value">${(s.total_exams || 0).toLocaleString()}</div>
          <div class="stat-label">Симуляций экзамена</div>
        </div>
      </div>
      <div class="stat-card">
        <span class="stat-icon">🗂</span>
        <div class="stat-info">
          <div class="stat-value">${s.total_questions.toLocaleString()}</div>
          <div class="stat-label">Вопросов в базе</div>
        </div>
      </div>
      <div class="stats-section-title">🔥 Топ-5 популярных предметов</div>
      ${topRows}
      <div class="stats-section-title">👥 Реферальная программа</div>
      <div class="stat-card">
        <span class="stat-icon">🔗</span>
        <div class="stat-info">
          <div class="stat-value">${(s.total_referrals || 0).toLocaleString()}</div>
          <div class="stat-label">Переходов по реф. ссылкам</div>
        </div>
      </div>
      <div class="stat-card">
        <span class="stat-icon">👤</span>
        <div class="stat-info">
          <div class="stat-value">${(s.total_referrers || 0).toLocaleString()}</div>
          <div class="stat-label">Активных рефереров</div>
        </div>
      </div>
      <div class="stat-card">
        <span class="stat-icon">💰</span>
        <div class="stat-info">
          <div class="stat-value">${(s.referral_purchases || 0).toLocaleString()}</div>
          <div class="stat-label">Покупок через рефералку</div>
        </div>
      </div>
      <div class="stats-section-title">🏆 Топ рефереры</div>
      ${(s.top_referrers || []).map((r, i) =>
        `<div class="top-subject-row">
          <span class="top-subject-medal">${["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"][i] || i+1}</span>
          <span class="top-subject-name">${r.label}</span>
          <span class="top-subject-count">${r.invited} чел. / ${r.purchases} покупок</span>
        </div>`
      ).join("")}
      <div class="stats-section-title">📚 Вопросов по предметам</div>
      <div class="subject-grid">${subjectCards}</div>
    `;
  } catch(e) {
    container.innerHTML = '<div class="loading">Ошибка загрузки статистики</div>';
  }
}

// ==================== EVENTS ====================

document.getElementById("filter-subject").addEventListener("change", applyFilter);
document.getElementById("filter-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(applyFilter, 300);
});
document.getElementById("btn-back").addEventListener("click", () => { showScreen("screen-list"); applyFilter(); });
document.getElementById("btn-save").addEventListener("click", saveQuestion);
document.getElementById("btn-delete").addEventListener("click", deleteQuestion);

// ==================== START ====================
init();
