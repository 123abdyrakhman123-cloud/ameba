const app = document.getElementById('app');

// ==================== State ====================
let CONFIG = null;       // faculties, access, trials
let WEB_CONFIG = null;
let WEB_SESSION = null;
let examTimer = null;    // setInterval ref
let examTimeLeft = 0;    // seconds remaining
let examCurrentIndex = 0;
let examTotal = 0;
let examCurrentQuestion = null;
let currentTestQ = null; // current test question data
let testSubject = null;
let inviteHandled = false;

function escapeHTML(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[char]));
}

async function claimInvite() {
    if (inviteHandled || !WEB_SESSION) return;
    const code = new URLSearchParams(window.location.search).get('ref');
    if (!code) return;
    inviteHandled = true;
    const url = new URL(window.location.href);
    url.searchParams.delete('ref');
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
    try {
        const result = await api('POST', '/api/referral/claim', { code });
        if (result.claimed) window.setTimeout(() => window.alert('Реферальная ссылка привязана. Вам начислены приветственные баллы.'), 0);
    } catch (error) {
        console.error('Referral claim failed', error);
    }
}

// ==================== API Helper ====================
async function api(method, path, body = null) {
    const opts = {
        method,
        credentials: 'same-origin',
        headers: {},
    };
    if (body !== null) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    return res.json();
}

async function apiForm(path, values) {
    const res = await fetch(path, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams(values),
    });
    return res.json();
}

async function loadConfig() {
    if (!CONFIG) {
        CONFIG = await api('GET', '/api/config');
    }
    return CONFIG;
}

// ==================== Router ====================
function navigate(hash) {
    const nextHash = hash ? `#${hash}` : '';
    if (window.location.hash === nextHash) return route();
    window.history.pushState({}, '', `${window.location.pathname}${window.location.search}${nextHash}`);
    route();
}

function getRoute() {
    const hash = window.location.hash.slice(1).replace(/^\/+/, '') || '';
    const parts = hash.split('/');
    return { path: parts[0] || '', params: parts.slice(1) };
}

window.addEventListener('popstate', route);

const NAV_ITEMS = [
    ['home', 'Главная', 'home'], ['tests', 'Тесты', 'tests'], ['subjects', 'Предметы', 'subjects'],
    ['progress', 'Прогресс', 'progress'], ['rating', 'Рейтинг', 'rating'],
    ['cards', 'Карточки', 'cards'], ['profile', 'Профиль', 'profile'],
];
let searchVersion = 0;

function navIcon(name) {
    const paths = {
        home: '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
        tests: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h3"/>',
        subjects: '<path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5"/>',
        progress: '<path d="M4 19V5M4 19h17M8 16v-4M13 16V8M18 16V4"/>',
        rating: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3l-5.6 2.9 1.1-6.2L3 9.6l6.2-.9z"/>',
        cards: '<rect x="4" y="5" width="13" height="15" rx="2"/><path d="M8 3h11a2 2 0 0 1 2 2v12M8 10h5M8 14h5"/>',
        profile: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    };
    return `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths[name] || paths.home}</svg>`;
}

function renderShell(active, content, options = {}) {
    const desktopNav = NAV_ITEMS.map(([key, label, icon]) =>
        `<a class="side-link ${active === key ? 'is-active' : ''}" href="#${key}" onclick="navigate('${key}'); return false" ${active === key ? 'aria-current="page"' : ''}>${navIcon(icon)}<span>${label}</span></a>`
    ).join('');
    const mobileNav = ['home', 'tests', 'subjects', 'profile'].map(key => {
        const item = NAV_ITEMS.find(entry => entry[0] === key);
        return `<a class="mobile-link ${active === key ? 'is-active' : ''}" href="#${item[0]}" onclick="navigate('${item[0]}'); return false" aria-label="${item[1]}">${navIcon(item[2])}<span>${item[1]}</span></a>`;
    }).join('');
    const accountName = escapeHTML(WEB_SESSION?.display_name || 'Пользователь');
    app.innerHTML = `
        <div class="workspace-shell">
            <aside class="workspace-sidebar">
                <a class="workspace-brand" href="#home" onclick="navigate('home'); return false"><span class="brand-amoeba">А</span><span><strong>АМЁБА</strong><small>База знаний</small></span></a>
                <nav class="side-nav" aria-label="Основная навигация">${desktopNav}</nav>
                <div class="sidebar-spacer"></div>
                <a class="side-link side-support" href="#support" onclick="navigate('support'); return false">${navIcon('profile')}<span>Поддержка</span></a>
                <div class="sidebar-account"><span class="avatar-small">${accountName.slice(0, 1)}</span><span><strong>${accountName}</strong><small>${WEB_SESSION?.is_demo ? 'Демо-режим' : escapeHTML(WEB_SESSION?.provider === 'telegram' ? 'Telegram' : 'Google')}</small></span>${WEB_SESSION?.is_demo ? '<span class="demo-marker">Демо</span>' : ''}</div>
            </aside>
            <div class="workspace-main">
                <header class="workspace-topbar">
                    <form class="global-search" id="globalSearchForm" role="search">
                        <span class="search-symbol" aria-hidden="true">⌕</span>
                        <input id="globalSearch" type="search" autocomplete="off" placeholder="Поиск по предметам, темам, вопросам..." aria-label="Поиск по предметам и вопросам">
                        <button type="button" class="search-clear" id="searchClear" aria-label="Очистить поиск" title="Очистить поиск">×</button>
                        <div class="search-results" id="searchResults" hidden></div>
                    </form>
                    <div class="topbar-account"><span class="avatar-small">${accountName.slice(0, 1)}</span><span><strong>${accountName}</strong><small>${WEB_SESSION?.is_demo ? 'Демо' : 'Аккаунт'}</small></span>${WEB_SESSION?.is_demo ? '<span class="demo-marker">Демо</span>' : ''}</div>
                </header>
                <main class="workspace-content">${content}</main>
                ${options.rail || ''}
            </div>
            <nav class="mobile-nav" aria-label="Мобильная навигация">${mobileNav}</nav>
        </div>`;
    bindGlobalSearch();
}

function bindGlobalSearch() {
    const form = document.getElementById('globalSearchForm');
    const input = document.getElementById('globalSearch');
    const clear = document.getElementById('searchClear');
    if (!form || !input) return;
    let debounce;
    form.addEventListener('submit', event => event.preventDefault());
    input.addEventListener('input', () => {
        clearTimeout(debounce);
        const query = input.value.trim();
        clear.hidden = !query;
        if (query.length < 2) {
            document.getElementById('searchResults').hidden = true;
            return;
        }
        debounce = setTimeout(() => loadGlobalSearch(query), 220);
    });
    clear.addEventListener('click', () => {
        input.value = '';
        clear.hidden = true;
        document.getElementById('searchResults').hidden = true;
        input.focus();
    });
    document.addEventListener('click', event => {
        if (!form.contains(event.target)) document.getElementById('searchResults')?.setAttribute('hidden', '');
    }, { once: true });
}

async function loadGlobalSearch(query) {
    const version = ++searchVersion;
    const result = document.getElementById('searchResults');
    if (!result) return;
    result.hidden = false;
    result.innerHTML = '<div class="search-message">Поиск...</div>';
    try {
        const data = await api('GET', `/api/search?q=${encodeURIComponent(query)}`);
        if (version !== searchVersion || !result.isConnected) return;
        const rows = [
            ...(data.subjects || []).map(item => `<button class="search-result" type="button" onclick="navigate('tests/${encodeURIComponent(item.key)}')"><strong>${escapeHTML(item.name)}</strong><small>${item.question_count} вопросов</small></button>`),
            ...(data.questions || []).map(item => `<button class="search-result" type="button" onclick="navigate('tests/${encodeURIComponent(item.subject)}')"><strong>${escapeHTML(item.subject_name)}</strong><span>${escapeHTML(item.snippet)}</span></button>`),
        ];
        result.innerHTML = rows.length ? rows.join('') : '<div class="search-message">Ничего не найдено</div>';
    } catch (error) {
        result.innerHTML = '<div class="search-message">Поиск временно недоступен</div>';
    }
}

function formatAccuracy(value) {
    return value == null ? '—' : `${Math.round(value)}%`;
}

function subjectMark(subject, index) {
    return `<span class="subject-mark subject-mark-${index % 5}" aria-hidden="true">${escapeHTML((subject.name || subject.key || 'П').replace(/[^А-Яа-яA-Za-z]/g, '').slice(0, 1) || 'П')}</span>`;
}

async function renderDashboard() {
    app.innerHTML = '<div class="loading">Загружаем вашу базу знаний...</div>';
    const [dashboard, progress, rating] = await Promise.all([
        api('GET', '/api/dashboard'), api('GET', '/api/progress'), api('GET', '/api/leaderboard'),
    ]);
    if (dashboard.error || progress.error) throw new Error('Dashboard data unavailable');
    const accuracy = progress.summary.accuracy_percent;
    const recent = dashboard.recent_exams || [];
    const subjects = dashboard.subjects || [];
    const picks = [...subjects].sort((a, b) => b.question_count - a.question_count).slice(0, 5);
    const totalAnswered = progress.summary.answered || 0;
    const recentHtml = recent.length ? recent.slice(0, 3).map(item => `
        <a class="recent-row" href="#exam-result/${item.id}" onclick="navigate('exam-result/${item.id}'); return false"><span class="recent-dot"></span><span><strong>${escapeHTML(item.subject)}</strong><small>${item.correct} из ${item.answered} правильных · ${escapeHTML(item.completed_at.slice(0, 10))}</small></span><span class="recent-score">${item.max_score ? Math.round(item.score * 100 / item.max_score) : 0}%</span></a>`).join('') : '<div class="empty-inline"><strong>История пока пустая</strong><span>Завершите первый экзамен, чтобы увидеть результат здесь.</span></div>';
    const subjectHtml = picks.length ? picks.map((subject, index) => `
        <a class="subject-card" href="#subject/${encodeURIComponent(subject.key)}">${subjectMark(subject, index)}<span class="subject-card-copy"><strong>${escapeHTML(subject.name)}</strong><small>${subject.question_count.toLocaleString('ru-RU')} вопросов</small></span><span class="subject-chevron" aria-hidden="true">›</span></a>`).join('') : '<div class="empty-inline">Вопросы пока не добавлены.</div>';
    const rankText = rating.rank ? `Место ${rating.rank}` : rating.enabled ? 'Рейтинг обновится, когда появятся участники' : 'Включите участие на странице рейтинга';
    const rail = `<aside class="workspace-rail">
        <section class="rail-panel progress-panel"><div class="panel-heading"><h2>Точность ответов</h2><a href="#progress">Подробнее</a></div><div class="accuracy-ring" style="--accuracy:${accuracy || 0}%"><span>${formatAccuracy(accuracy)}</span></div><p>${accuracy == null ? 'Появится после первого экзамена' : `По ${progress.summary.exam_count} завершённым экзаменам`}</p><div class="rail-divider"></div><div class="rail-metric"><span>Ответов сегодня</span><strong>${dashboard.activity.answers_today}</strong></div><div class="rail-metric"><span>Серия занятий</span><strong>${dashboard.activity.streak_days} дн.</strong></div></section>
        <section class="rail-panel ranking-panel"><div class="panel-heading"><h2>Мой рейтинг</h2><span class="trophy-mark" aria-hidden="true">★</span></div><strong class="rank-position">${escapeHTML(rankText)}</strong><p>${rating.enabled ? `${rating.entries?.find(item => item.rank === rating.rank)?.points ?? 0} баллов` : 'Псевдоним можно выбрать в настройках рейтинга'}</p><a class="text-link" href="#rating">Открыть рейтинг <span aria-hidden="true">→</span></a></section>
        <section class="mascot-note"><img src="/static/assets/ameba-mascot.webp" alt="Амёба читает книгу" loading="lazy"><p>Шаг за шагом<br>к уверенности</p></section>
    </aside>`;
    const content = `
        <section class="dashboard-hero">
            <div class="hero-copy"><p class="eyebrow">ВАША БАЗА ЗНАНИЙ</p><h1>Подготовка<br>к экзаменам</h1><p>Учитесь в своём темпе. Отслеживайте прогресс и возвращайтесь к сложным вопросам.</p><div class="hero-actions"><button class="action-primary" type="button" onclick="navigate('tests')">Начать подготовку <span aria-hidden="true">→</span></button><button class="action-secondary" type="button" onclick="navigate('subjects')">Все предметы</button></div></div>
            <img class="hero-mascot" src="/static/assets/ameba-mascot.webp" alt="Амёба изучает медицинские материалы">
        </section>
        <section class="metric-strip" aria-label="Статистика каталога">
            <div class="metric-item"><span class="metric-icon metric-icon-green">✳</span><span><strong>${dashboard.catalog.question_count.toLocaleString('ru-RU')}</strong><small>вопросов</small></span></div>
            <div class="metric-item"><span class="metric-icon metric-icon-teal">▦</span><span><strong>${dashboard.catalog.subject_count}</strong><small>предметов</small></span></div>
            <div class="metric-item"><span class="metric-icon metric-icon-blue">✓</span><span><strong>${dashboard.access.subject_count}</strong><small>полный доступ</small></span></div>
            <div class="metric-item"><span class="metric-icon metric-icon-amber">◷</span><span><strong>${totalAnswered.toLocaleString('ru-RU')}</strong><small>ответов в экзаменах</small></span></div>
        </section>
        <section class="dashboard-section"><div class="section-heading"><div><p class="eyebrow">КАТАЛОГ</p><h2>Предметы</h2></div><a class="text-link" href="#subjects">Все предметы <span aria-hidden="true">→</span></a></div><div class="subject-grid">${subjectHtml}</div></section>
        <section class="dashboard-section tests-section"><div class="section-heading"><div><p class="eyebrow">ПРАКТИКА</p><h2>Продолжить обучение</h2></div><a class="text-link" href="#tests">Все тесты <span aria-hidden="true">→</span></a></div><div class="recommendation-list">${picks.slice(0, 3).map((subject, index) => `<article class="recommendation-row">${subjectMark(subject, index)}<span class="recommendation-copy"><strong>${escapeHTML(subject.name)}</strong><small>${subject.question_count} вопросов в каталоге · ${subject.access ? 'полный доступ' : 'доступны пробные вопросы'}</small></span><button class="small-action" type="button" onclick="navigate('tests/${encodeURIComponent(subject.key)}')">Открыть <span aria-hidden="true">→</span></button></article>`).join('') || '<div class="empty-inline">Тесты появятся, когда в каталоге будут вопросы.</div>'}</div></section>
        <section class="dashboard-section recent-section"><div class="section-heading"><div><p class="eyebrow">ВАШИ ЗАНЯТИЯ</p><h2>Недавние экзамены</h2></div><a class="text-link" href="#progress">История <span aria-hidden="true">→</span></a></div><div class="recent-list">${recentHtml}</div></section>`;
    renderShell('home', content, { rail });
}

async function renderSubjectCatalog() {
    app.innerHTML = '<div class="loading">Загружаем предметы...</div>';
    const data = await api('GET', '/api/dashboard');
    if (data.error) throw new Error('Catalog unavailable');
    const subjects = data.subjects || [];
    const content = `<section class="page-intro"><p class="eyebrow">КАТАЛОГ</p><h1>Предметы</h1><p>${data.catalog.subject_count} предмета · ${data.catalog.question_count.toLocaleString('ru-RU')} вопросов</p></section><div class="catalog-subject-grid">${subjects.length ? subjects.map((subject, index) => `<a class="catalog-subject" href="#subject/${encodeURIComponent(subject.key)}">${subjectMark(subject, index)}<span><strong>${escapeHTML(subject.name)}</strong><small>${subject.question_count} вопросов · ${subject.access ? 'полный доступ' : 'пробный режим'}</small></span><span class="subject-chevron">›</span></a>`).join('') : '<div class="empty-state"><h2>Каталог пуст</h2><p>Когда вопросы появятся, они будут доступны здесь.</p></div>'}</div>`;
    renderShell('subjects', content);
}

async function renderTests(filter = '') {
    app.innerHTML = '<div class="loading">Загружаем тесты...</div>';
    const [data, config] = await Promise.all([api('GET', '/api/dashboard'), loadConfig()]);
    if (data.error) throw new Error('Test catalog unavailable');
    const subjects = (data.subjects || []).filter(item => !filter || item.key === filter);
    const content = `<section class="page-intro"><p class="eyebrow">ТРЕНИРОВКА</p><h1>${filter ? 'Тесты по предмету' : 'Тесты'}</h1><p>Выберите предмет и продолжайте подготовку по реальным вопросам каталога.</p></section><div class="test-catalog">${subjects.length ? subjects.map((subject, index) => `<article class="test-subject-row">${subjectMark(subject, index)}<div class="test-subject-copy"><strong>${escapeHTML(subject.name)}</strong><small>${subject.question_count.toLocaleString('ru-RU')} вопросов · ${subject.access ? 'полный доступ' : '5 пробных ответов'}</small></div><button class="small-action" type="button" onclick="navigate('test/${encodeURIComponent(subject.key)}')">Решать <span aria-hidden="true">→</span></button>${subject.access ? `<button class="icon-action" type="button" aria-label="Начать экзамен по ${escapeHTML(subject.name)}" title="Симуляция экзамена" onclick="navigate('exam-start/${encodeURIComponent(subject.key)}')">◷</button>` : ''}</article>`).join('') : '<div class="empty-state"><h2>Вопросов пока нет</h2><p>Для этого раздела еще нет доступного каталога.</p></div>'}</div>`;
    renderShell('tests', content);
}

async function renderSubjectDetail(subjectKey) {
    app.innerHTML = '<div class="loading">Открываем предмет...</div>';
    const [config, dashboard] = await Promise.all([loadConfig(), api('GET', '/api/dashboard')]);
    let subject = (dashboard.subjects || []).find(item => item.key === subjectKey);
    if (!subject) return renderSubjectCatalog();
    const access = !!config.access[subjectKey];
    const remaining = Math.max(0, 5 - (config.trials[subjectKey] || 0));
    const content = `<section class="page-intro"><a class="back-link" href="#subjects">← Предметы</a><p class="eyebrow">ПРЕДМЕТ</p><h1>${escapeHTML(subject.name)}</h1><p>${subject.question_count.toLocaleString('ru-RU')} вопросов в каталоге</p></section><section class="subject-detail-panel"><div class="detail-status"><span class="status-dot ${access ? 'status-dot-ready' : ''}"></span>${access ? 'Полный доступ' : `Пробный доступ: осталось ${remaining} вопросов`}</div><div class="detail-actions"><button class="action-primary" type="button" ${!access && remaining <= 0 ? 'disabled' : ''} onclick="navigate('test/${encodeURIComponent(subjectKey)}')">Начать тест <span aria-hidden="true">→</span></button>${access ? `<button class="action-secondary" type="button" onclick="navigate('exam-start/${encodeURIComponent(subjectKey)}')">Симуляция экзамена</button>` : `<button class="action-secondary" type="button" onclick="navigate('purchase/${encodeURIComponent(subjectKey)}')">Как получить доступ</button>`}</div></section>`;
    renderShell('subjects', content);
}

async function renderProgress() {
    app.innerHTML = '<div class="loading">Загружаем прогресс...</div>';
    const [progress, dashboard] = await Promise.all([api('GET', '/api/progress'), api('GET', '/api/dashboard')]);
    if (progress.error) throw new Error('Progress unavailable');
    const summary = progress.summary;
    const days = progress.activity_by_day.slice(-14);
    const maxCount = Math.max(1, ...days.map(day => day.count));
    const activity = days.length ? `<div class="activity-chart" role="img" aria-label="Активность по дням">${days.map(day => `<div class="activity-column"><span class="activity-bar" style="height:${Math.max(5, day.count / maxCount * 100)}%" title="${day.count} действий"></span><small>${day.date.slice(5)}</small></div>`).join('')}</div>` : '<div class="empty-state"><h2>Активность появится здесь</h2><p>Пройдите тест или экзамен, чтобы начать историю занятий.</p><button class="action-primary" onclick="navigate(\'tests\')">Выбрать тест</button></div>';
    const exams = progress.exams.length ? progress.exams.map(exam => `<a class="exam-history-row" href="#exam-result/${exam.id}" onclick="navigate('exam-result/${exam.id}'); return false"><span class="history-date">${escapeHTML((exam.completed_at || '').slice(0,10))}</span><span class="history-subject"><strong>${escapeHTML(exam.subject)}</strong><small>${exam.correct}/${exam.answered} правильных · ${exam.elapsed_seconds} сек</small></span><strong class="history-percent">${exam.max_score ? Math.round(exam.score * 100 / exam.max_score) : 0}%</strong><span aria-hidden="true">›</span></a>`).join('') : '<div class="empty-inline"><strong>Завершённых экзаменов пока нет</strong><span>Первый результат появится в этой истории.</span></div>';
    const subjectRows = progress.subjects.length ? progress.subjects.map(subject => {
        const subjectName = (dashboard.subjects || []).find(item => item.key === subject.key)?.name || subject.key;
        return `<div class="subject-progress-row"><span><strong>${escapeHTML(subjectName)}</strong><small>${subject.exam_count} экзаменов · ${subject.answered} ответов</small></span><span class="subject-accuracy">${formatAccuracy(subject.accuracy_percent)}</span></div>`;
    }).join('') : '<div class="empty-inline">Данные по предметам появятся после первого завершённого экзамена.</div>';
    const content = `<section class="page-intro"><p class="eyebrow">ВАША СТАТИСТИКА</p><h1>Прогресс</h1><p>Результаты завершённых веб-экзаменов и сохранённая активность.</p></section><section class="progress-kpis"><div><small>Экзаменов</small><strong>${summary.exam_count}</strong></div><div><small>Ответов</small><strong>${summary.answered}</strong></div><div><small>Правильных</small><strong>${summary.correct}</strong></div><div><small>Точность</small><strong>${formatAccuracy(summary.accuracy_percent)}</strong></div><div><small>Серия</small><strong>${dashboard.activity.streak_days} дн.</strong></div></section><section class="dashboard-section"><div class="section-heading"><div><p class="eyebrow">ПО ДНЯМ</p><h2>Активность</h2></div><span class="result-muted">UTC</span></div><div class="activity-panel">${activity}</div></section><section class="dashboard-section"><div class="section-heading"><div><p class="eyebrow">ИСТОРИЯ</p><h2>Экзамены</h2></div></div><div class="exam-history-list">${exams}</div></section><section class="dashboard-section"><div class="section-heading"><div><p class="eyebrow">СРАВНЕНИЕ</p><h2>По предметам</h2></div></div><div class="subject-progress-list">${subjectRows}</div></section>`;
    renderShell('progress', content);
}

async function renderRating() {
    app.innerHTML = '<div class="loading">Загружаем рейтинг...</div>';
    const data = await api('GET', '/api/leaderboard');
    if (data.error) throw new Error('Leaderboard unavailable');
    const rows = (data.entries || []).map(entry => `<div class="leaderboard-row ${entry.display_name === data.display_name && data.enabled ? 'leaderboard-self' : ''}"><span class="leaderboard-rank">${entry.rank}</span><strong>${escapeHTML(entry.display_name)}</strong><span>${entry.points.toLocaleString('ru-RU')} баллов</span></div>`).join('');
    const demo = WEB_SESSION?.is_demo;
    const content = `<section class="page-intro"><p class="eyebrow">УЧАСТНИКИ</p><h1>Рейтинг</h1><p>Показываются только пользователи, которые сами включили участие и выбрали псевдоним.</p></section><section class="rating-optin-panel"><div><h2>Участие в рейтинге</h2><p>${demo ? 'Демо-аккаунты не участвуют в рейтинге.' : 'Ваш Telegram ID, username и email другим пользователям не показываются.'}</p></div><label class="rating-name-label" for="leaderboardName">Псевдоним</label><div class="rating-preference-row"><input id="leaderboardName" type="text" maxlength="24" value="${escapeHTML(data.display_name || '')}" placeholder="Например, Руслан"><button class="action-primary" type="button" ${demo ? 'disabled' : ''} onclick="saveLeaderboardPreference()">${data.enabled ? 'Сохранить' : 'Включить участие'}</button></div>${data.enabled ? '<button class="text-button" type="button" onclick="disableLeaderboard()">Скрыть меня из рейтинга</button>' : ''}<p class="form-status" id="leaderboardStatus" role="status"></p></section><section class="dashboard-section"><div class="section-heading"><div><p class="eyebrow">ТОП УЧАСТНИКОВ</p><h2>Таблица рейтинга</h2></div><span class="result-muted">${rows ? `${data.entries.length} участников` : 'Пока пусто'}</span></div><div class="leaderboard-list">${rows || '<div class="empty-state"><h2>Рейтинг пока пустой</h2><p>Он заполнится, когда пользователи добровольно включат участие.</p></div>'}</div></section>`;
    renderShell('rating', content);
}

async function saveLeaderboardPreference() {
    const input = document.getElementById('leaderboardName');
    const status = document.getElementById('leaderboardStatus');
    const button = document.querySelector('.rating-preference-row .action-primary');
    if (!input || !status) return;
    if (button) button.disabled = true;
    status.textContent = 'Сохраняем...';
    try {
        const result = await api('POST', '/api/leaderboard/visibility', { enabled: true, display_name: input.value });
        if (result.error) throw new Error(result.error);
        status.textContent = 'Вы участвуете в рейтинге.';
        await renderRating();
    } catch (error) {
        status.textContent = error.message || 'Не удалось сохранить настройки.';
        if (button) button.disabled = false;
    }
}

async function disableLeaderboard() {
    const input = document.getElementById('leaderboardName');
    const status = document.getElementById('leaderboardStatus');
    const result = await api('POST', '/api/leaderboard/visibility', { enabled: false, display_name: input?.value || '' });
    if (result.error) {
        if (status) status.textContent = result.error;
        return;
    }
    await renderRating();
}

let flashcards = [];
let flashcardIndex = 0;
let flashcardSubject = '';
let flashcardFilter = null;
let flashcardRevealed = null;
let flashcardSubjects = [];

async function renderFlashcards(subject, state = null) {
    app.innerHTML = '<div class="loading">Загружаем карточки...</div>';
    const profile = await api('GET', '/api/profile');
    const available = (profile.access || []).filter(item => item.active);
    flashcardSubjects = available;
    if (!subject) subject = available[0]?.subject;
    if (!subject) {
        return renderShell('cards', '<div class="empty-state"><h2>Нет предметов с доступом</h2><p>Карточки доступны для предметов, к которым у вашего аккаунта есть доступ.</p><button class="action-primary" onclick="navigate(\'subjects\')">Открыть предметы</button></div>');
    }
    if (!available.some(item => item.subject === subject)) {
        return renderShell('cards', '<div class="empty-state"><h2>Нет доступа к предмету</h2><p>Выберите предмет, доступный аккаунту.</p><button class="action-secondary" onclick="navigate(\'profile\')">Профиль</button></div>');
    }
    const query = new URLSearchParams({ subject });
    if (state) query.set('state', state);
    const data = await api('GET', `/api/flashcards?${query}`);
    if (data.error) throw new Error(data.error);
    flashcards = data.cards || [];
    flashcardSubject = subject;
    flashcardFilter = state;
    flashcardIndex = 0;
    flashcardRevealed = null;
    renderFlashcardPage(available.find(item => item.subject === subject)?.name || subject);
}

function renderFlashcardPage(subjectName) {
    const filters = [['all', 'Все'], ['new', 'Новые'], ['repeat', 'Повторить'], ['known', 'Знаю']];
    const filterHtml = filters.map(([key, label]) => {
        const active = (key === 'all' && !flashcardFilter) || key === flashcardFilter;
        const path = key === 'all' ? `cards/${encodeURIComponent(flashcardSubject)}` : `cards/${encodeURIComponent(flashcardSubject)}/${key}`;
        return `<button class="segmented-button ${active ? 'is-active' : ''}" type="button" onclick="navigate('${path}')">${label}</button>`;
    }).join('');
    let cardContent;
    const card = flashcards[flashcardIndex];
    if (!card) {
        cardContent = `<div class="empty-state"><h2>${flashcardFilter === 'new' ? 'Новые карточки закончились' : 'Карточек пока нет'}</h2><p>Выберите другой фильтр или вернитесь к предметам.</p><button class="action-secondary" onclick="navigate('subjects')">Все предметы</button></div>`;
    } else {
        cardContent = `<article class="flashcard"><div class="flashcard-meta"><span>${escapeHTML(subjectName)}</span><span>${flashcardIndex + 1} / ${flashcards.length}</span></div><p class="flashcard-question">${escapeHTML(card.question)}</p>${flashcardRevealed ? `<div class="flashcard-answer"><small>ПРАВИЛЬНЫЙ ОТВЕТ</small><strong>${escapeHTML(flashcardRevealed.answer || `Вариант ${flashcardRevealed.correct_option}`)}</strong>${flashcardRevealed.explanation ? `<p>${escapeHTML(flashcardRevealed.explanation)}</p>` : ''}</div><div class="flashcard-actions"><button class="action-secondary" type="button" onclick="saveFlashcardReview('repeat')">Повторить</button><button class="action-primary" type="button" onclick="saveFlashcardReview('known')">Знаю <span aria-hidden="true">→</span></button></div>` : `<button class="action-primary reveal-action" type="button" onclick="revealFlashcard(${card.question_id})">Показать ответ <span aria-hidden="true">↓</span></button>`}</article>`;
    }
    const subjectOptions = flashcardSubjects.map(item => `<option value="${escapeHTML(item.subject)}">${escapeHTML(item.name)}</option>`);
    const content = `<section class="page-intro"><p class="eyebrow">АКТИВНОЕ ПОВТОРЕНИЕ</p><h1>Карточки</h1><p>Вспомните ответ, затем откройте его и отметьте, нужно ли повторение.</p></section><div class="flashcard-toolbar"><label for="flashcardSubject">Предмет</label><select id="flashcardSubject" onchange="navigate('cards/'+this.value)">${subjectOptions.join('')}</select><div class="segmented-control" role="group" aria-label="Фильтр карточек">${filterHtml}</div></div>${cardContent}`;
    renderShell('cards', content);
    const select = document.getElementById('flashcardSubject');
    if (select) select.value = flashcardSubject;
}

async function revealFlashcard(questionId) {
    const result = await api('GET', `/api/flashcards/${questionId}/reveal`);
    if (result.error) return renderShell('cards', `<div class="empty-state"><h2>Не удалось раскрыть ответ</h2><p>${escapeHTML(result.error)}</p></div>`);
    flashcardRevealed = result;
    const profile = await api('GET', '/api/profile');
    const subject = (profile.access || []).find(item => item.subject === flashcardSubject);
    renderFlashcardPage(subject?.name || flashcardSubject);
}

async function saveFlashcardReview(state) {
    const card = flashcards[flashcardIndex];
    if (!card) return;
    const reviewKey = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const result = await api('POST', `/api/flashcards/${card.question_id}/review`, { state, review_key: reviewKey });
    if (result.error) {
        const current = document.querySelector('.flashcard-actions');
        if (current) current.insertAdjacentHTML('beforeend', `<p class="form-status">${escapeHTML(result.error)}</p>`);
        return;
    }
    flashcards.splice(flashcardIndex, 1);
    flashcardRevealed = null;
    const profile = await api('GET', '/api/profile');
    const subject = (profile.access || []).find(item => item.subject === flashcardSubject);
    renderFlashcardPage(subject?.name || flashcardSubject);
}

async function renderProfile() {
    app.innerHTML = '<div class="loading">Загружаем профиль...</div>';
    const profile = await api('GET', '/api/profile');
    if (profile.error) throw new Error('Profile unavailable');
    const providerName = profile.provider === 'telegram' ? 'Telegram' : 'Google';
    const access = profile.access || [];
    const content = `<section class="page-intro"><p class="eyebrow">АККАУНТ</p><h1>Профиль</h1><p>Данные веб-аккаунта и доступ к предметам.</p></section><section class="profile-panel"><div class="profile-identity"><span class="profile-avatar">${escapeHTML((profile.display_name || 'П').slice(0,1))}</span><div><strong>${escapeHTML(profile.display_name)}</strong><small>${providerName}${profile.is_demo ? ' · Демо-режим' : ''}</small></div>${profile.is_demo ? '<span class="demo-marker">Демо</span>' : ''}</div><div class="profile-info-row"><span>Способ входа</span><strong>${providerName}</strong></div><div class="profile-info-row"><span>Статус</span><strong>${profile.is_demo ? 'Демо-аккаунт' : 'Подключён'}</strong></div></section><section class="dashboard-section"><div class="section-heading"><div><p class="eyebrow">ВАШ ДОСТУП</p><h2>Предметы</h2></div><span class="result-muted">${access.filter(item => item.active).length} доступны</span></div><div class="profile-access-list">${access.length ? access.map(item => `<div class="profile-access-row"><span>${escapeHTML(item.name)}</span><strong class="${item.active ? 'access-active' : 'access-inactive'}">${item.active ? 'Доступен' : 'Нет доступа'}</strong></div>`).join('') : '<div class="empty-inline">Предметы не найдены.</div>'}</div></section><section class="profile-actions"><button class="action-secondary logout-button" type="button" onclick="logoutWebSession()">Выйти из аккаунта</button><p class="form-status" id="profileStatus" role="status"></p></section>`;
    renderShell('profile', content);
}

async function logoutWebSession() {
    const button = document.querySelector('.logout-button');
    const status = document.getElementById('profileStatus');
    if (button) button.disabled = true;
    try {
        const result = await api('POST', '/api/session/logout', {});
        if (result.error) throw new Error(result.error);
        WEB_SESSION = null;
        CONFIG = null;
        renderLogin();
    } catch (error) {
        if (button) button.disabled = false;
        if (status) status.textContent = 'Не удалось выйти. Попробуйте снова.';
    }
}

async function route() {
    if (!WEB_SESSION) return renderLogin();
    const { path, params } = getRoute();

    // Clean up exam timer when leaving exam
    if (path !== 'exam' && examTimer) {
        clearInterval(examTimer);
        examTimer = null;
    }

    try {
        switch (path) {
            case '':
            case 'home':
                await renderDashboard();
                break;
            case 'tests':
                await renderTests(params[0]);
                break;
            case 'subjects':
                if (params.length) await renderSubjects(params[0], parseInt(params[1]));
                else await renderSubjectCatalog();
                break;
            case 'progress':
                await renderProgress();
                break;
            case 'rating':
                await renderRating();
                break;
            case 'cards':
                await renderFlashcards(params[0], params[1]);
                break;
            case 'profile':
                await renderProfile();
                break;
            case 'subject':
                await renderSubjectDetail(params[0]);
                break;
            case 'courses':
                await renderCourses(params[0]);
                break;
            case 'subjects':
                await renderSubjects(params[0], parseInt(params[1]));
                break;
            case 'modes':
                await renderModes(params[0], parseInt(params[1]), params[2]);
                break;
            case 'exam-start':
                await renderExamStart(params[0]);
                break;
            case 'exam':
                await renderExam(params[0]);
                break;
            case 'exam-result':
                await renderExamResult(params[0]);
                break;
            case 'review':
                await renderReview(parseInt(params[0] || '0'));
                break;
            case 'test':
                await renderTest(params[0]);
                break;
            case 'purchase':
                await renderPurchase(params[0]);
                break;
            case 'support':
                await renderSupport();
                break;
            case 'referral':
                await renderReferral();
                break;
            default:
                await renderShell(path, '<section class="empty-state"><h2>Раздел обновляется</h2><p>Эта страница появится в ближайшем обновлении.</p></section>');
        }
    } catch (e) {
        console.error(e);
        app.innerHTML = '<div class="loading">Ошибка загрузки. Попробуйте снова.</div>';
    }
}

function renderLogin(message = '') {
    app.innerHTML = `
        <section class="login-shell">
            <div class="login-brand"><span class="brand-mark">А</span><div><strong>АМЁБА</strong><span>Подготовка к экзаменам</span></div></div>
            <div class="login-content">
                <p class="login-eyebrow">ОБУЧЕНИЕ И ПРОГРЕСС</p>
                <h1>Войдите в аккаунт</h1>
                <p class="login-subtitle">Продолжайте подготовку с любого устройства.</p>
                <div class="login-provider-block">
                <div id="telegramLoginWidget" class="telegram-login-widget"><span>Telegram Login Widget</span></div>
                <div id="googleSignInButton" class="google-signin-button"></div>
                ${WEB_CONFIG.demo_login_enabled ? '<button class="demo-login-button" id="demoLoginButton" type="button">Войти в демо-режим</button>' : ''}
                </div>
                <div class="login-reminder"><strong>Уже покупали доступ в боте?</strong><span>Если вы уже покупали доступ в боте, войдите через Telegram, чтобы увидеть свои покупки и прогресс.</span></div>
                <p class="login-separation">Google создаёт отдельный веб-аккаунт, покупки Telegram в него не переносятся.</p>
                <p class="login-error" id="loginError" role="status"></p>
            </div>
            <footer class="login-footer">АМЁБА · Медицинская подготовка</footer>
        </section>`;
    document.getElementById('loginError').textContent = message;
    loadTelegramWidget();
    loadGoogleIdentity();
    const demoButton = document.getElementById('demoLoginButton');
    if (demoButton) demoButton.addEventListener('click', () => completeLogin('/api/session/demo', {})
        .catch(() => showLoginError('Не удалось войти в демо-режим.')));
}

function showLoginError(message) {
    const node = document.getElementById('loginError');
    if (node) node.textContent = message;
}

async function completeLogin(path, payload) {
    const result = await api('POST', path, payload);
    if (!result.success) {
        showLoginError(result.error || 'Не удалось войти. Проверьте данные и попробуйте снова.');
        return;
    }
    const session = await api('GET', '/api/session');
    if (!session.authenticated) {
        showLoginError('Не удалось создать сессию. Попробуйте ещё раз.');
        return;
    }
    WEB_SESSION = session;
    await claimInvite();
    route();
}

function loadTelegramWidget() {
    window.onTelegramAuth = user => completeLogin('/api/session/telegram', user)
        .catch(() => showLoginError('Не удалось связаться с сервером.'));
    const host = document.getElementById('telegramLoginWidget');
    if (!host || !WEB_CONFIG.telegram_bot_username) return;
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://telegram.org/js/telegram-widget.js?22';
    script.setAttribute('data-telegram-login', WEB_CONFIG.telegram_bot_username);
    script.setAttribute('data-size', 'large');
    script.setAttribute('data-userpic', 'false');
    script.setAttribute('data-onauth', 'onTelegramAuth(user)');
    host.replaceChildren(script);
}

function readCookie(name) {
    const prefix = `${name}=`;
    const item = document.cookie.split('; ').find(value => value.startsWith(prefix));
    return item ? decodeURIComponent(item.slice(prefix.length)) : '';
}

function loadGoogleIdentity() {
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.onload = () => {
        window.google.accounts.id.initialize({
            client_id: WEB_CONFIG.google_client_id,
            callback: response => apiForm('/api/session/google', {
                credential: response.credential,
                g_csrf_token: readCookie('g_csrf_token'),
            }).then(result => {
                if (!result.success) showLoginError(result.error || 'Не удалось войти через Google.');
                else return api('GET', '/api/session').then(async session => {
                    WEB_SESSION = session.authenticated ? session : null;
                    if (WEB_SESSION) { await claimInvite(); route(); }
                });
            }).catch(() => showLoginError('Не удалось связаться с сервером.')),
        });
        const button = document.getElementById('googleSignInButton');
        if (button) window.google.accounts.id.renderButton(button, {
            theme: 'outline', size: 'large', text: 'continue_with', shape: 'rectangular', width: 280,
        });
    };
    document.head.appendChild(script);
}

async function initializeWebClient() {
    try {
        WEB_CONFIG = await api('GET', '/api/config');
        const session = await api('GET', '/api/session');
        WEB_SESSION = session.authenticated ? session : null;
        if (WEB_SESSION) { await claimInvite(); route(); }
        else renderLogin();
    } catch (error) {
        console.error(error);
        app.innerHTML = '<div class="loading">Не удалось подключиться. Обновите страницу.</div>';
    }
}

// ==================== Views ====================

// --- Faculties ---
async function renderFaculties() {
    const cfg = await loadConfig();
    const [announcements, promo] = await Promise.all([
        api('GET', '/api/announcements'), api('GET', '/api/promo'),
    ]);
    let html = `<div class="header"><h1>AMEBA</h1><p>Подготовка к экзаменам</p>${WEB_SESSION.is_demo ? '<span class="demo-marker">Демо</span>' : ''}</div>`;
    if (promo.text) html += `<div class="info-box info">${escapeHTML(promo.text)}</div>`;
    for (const item of announcements.announcements || []) {
        html += `<section class="info-box info"><strong>${escapeHTML(item.title)}</strong><div>${escapeHTML(item.body)}</div></section>`;
    }
    html += '<div class="btn-list">';
    for (const [key, fac] of Object.entries(cfg.faculties)) {
        html += `<button class="btn" onclick="navigate('courses/${key}')">${fac.name}</button>`;
    }
    html += `<button class="btn" onclick="navigate('referral')">💎 Баллы и рефералка</button>`;
    html += `<button class="btn" onclick="navigate('support')">📩 Поддержка</button>`;
    if (WEB_SESSION.is_admin) html += '<a class="btn" href="/admin">Администрирование</a>';
    html += '</div>';
    app.innerHTML = html;
}

// --- Courses ---
async function renderCourses(facKey) {
    const cfg = await loadConfig();
    const fac = cfg.faculties[facKey];
    if (!fac) return navigate('');

    let html = `<div class="header"><h1>${fac.name}</h1><p>Выберите курс</p></div>`;
    html += '<div class="btn-list">';
    for (let i = 1; i <= fac.courses; i++) {
        const subjects = fac.subjects[String(i)] || [];
        const hasSub = subjects.length > 0;
        const hint = hasSub ? '' : '<div class="btn-hint">Скоро</div>';
        const cls = hasSub ? 'btn' : 'btn btn-disabled';
        html += `<button class="${cls}" onclick="navigate('subjects/${facKey}/${i}')">
            📚 ${i} курс${hint}
        </button>`;
    }
    html += '</div>';
    app.innerHTML = html;
}

// --- Subjects ---
async function renderSubjects(facKey, courseNum) {
    const cfg = await loadConfig();
    const fac = cfg.faculties[facKey];
    if (!fac) return navigate('');

    const subjects = fac.subjects[String(courseNum)] || [];
    let html = `<div class="header"><h1>${fac.name}</h1><p>${courseNum} курс</p></div>`;
    html += '<div class="btn-list">';
    for (const subj of subjects) {
        const hasAccess = cfg.access[subj.key];
        const badge = hasAccess ? '' : '<div class="btn-hint">Пробный доступ: 5 вопросов</div>';
        html += `<button class="btn" onclick="navigate('modes/${facKey}/${courseNum}/${subj.key}')">
            ${subj.name}${badge}
        </button>`;
    }
    html += '</div>';
    app.innerHTML = html;
}

// --- Modes ---
async function renderModes(facKey, courseNum, subject) {
    const cfg = await loadConfig();
    const fac = cfg.faculties[facKey];
    const hasAccess = cfg.access[subject];
    const trialUsed = cfg.trials[subject] || 0;
    const trialLeft = Math.max(0, 5 - trialUsed);

    // Find subject name
    const subjects = fac.subjects[String(courseNum)] || [];
    const subjData = subjects.find(s => s.key === subject);
    const subjName = subjData ? subjData.name : subject;

    let html = `<div class="header"><h1>${subjName}</h1><p>Выберите режим</p></div>`;

    if (!hasAccess) {
        html += `<div class="info-box warning">🎁 Пробный режим: осталось ${trialLeft} бесплатных вопросов</div>`;
    }

    html += '<div class="btn-list">';

    // Exam — only with access
    if (hasAccess) {
        html += `<button class="btn" onclick="navigate('exam-start/${subject}')">
            📝 Симуляция экзамена
            <div class="btn-hint">50 вопросов, 75 минут</div>
        </button>`;
    } else {
        html += `<button class="btn btn-disabled">
            📝 Симуляция экзамена
            <div class="btn-hint">Доступно после оплаты</div>
        </button>`;
    }

    // Tests
    if (hasAccess || trialLeft > 0) {
        html += `<button class="btn" onclick="navigate('test/${subject}')">
            📖 Решать тесты
        </button>`;
    } else {
        html += `<button class="btn btn-disabled">
            📖 Решать тесты
            <div class="btn-hint">Пробный период закончился</div>
        </button>`;
    }

    // Purchase — всегда показываем если нет доступа
    if (!hasAccess) {
        html += `<button class="btn btn-primary" onclick="navigate('purchase/${subject}')">
            Как получить полный доступ
        </button>`;
    }

    html += `<button class="btn" onclick="navigate('support')">📩 Поддержка</button>`;
    html += '</div>';
    app.innerHTML = html;
}


// --- Exam Start Confirmation ---
async function renderExamStart(subject) {
    const content = `<section class="page-intro"><a class="back-link" href="#tests" onclick="navigate('tests'); return false">← Тесты</a><p class="eyebrow">ПОЛНОЦЕННЫЙ ЭКЗАМЕН</p><h1>Симуляция экзамена</h1><p>${escapeHTML(subject)} · время и количество вопросов определяются сервером для доступного каталога.</p></section><section class="subject-detail-panel"><div class="detail-status">75 минут · 2 балла за правильный ответ</div><div class="detail-actions"><button class="action-primary" id="startExamBtn" type="button" onclick="startExam('${escapeHTML(subject)}')">Начать экзамен <span aria-hidden="true">→</span></button></div></section>`;
    renderShell('tests', content);
}

async function startExam(subject) {
    const btn = document.getElementById('startExamBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Загрузка...'; }

    const res = await api('POST', '/api/exam/start', { subject });
    if (res.error) {
        app.innerHTML = `<div class="info-box warning">${res.error}</div>
            <button class="btn" onclick="navigate('')">В меню</button>`;
        return;
    }
    examTotal = res.total_questions;
    navigate('exam/' + subject);
}

// --- Exam ---
async function renderExam() {
    await loadExamQuestion();
}

async function loadExamQuestion() {
    const res = await api('GET', '/api/exam/question');

    if (res.expired || res.finished) {
        await finishExam();
        return;
    }
    if (res.error) {
        renderShell('tests', `<div class="empty-state"><h2>Экзамен не найден</h2><p>${escapeHTML(res.error)}</p><button class="action-secondary" onclick="navigate('tests')">К тестам</button></div>`);
        return;
    }
    examCurrentIndex = res.index ?? Math.max(0, (res.question_number || 1) - 1);
    examTotal = res.total;
    examCurrentQuestion = res.question;
    examTimeLeft = res.time_remaining;
    renderExamQuestion(res.question, res.selected_option);
    startExamTimer();
}

function renderExamQuestion(question, selectedOption) {
    const progress = examTotal ? Math.round(((examCurrentIndex + 1) / examTotal) * 100) : 0;
    const options = question.options.map((option, index) => `<button class="exam-option ${selectedOption === index + 1 ? 'is-selected' : ''}" type="button" onclick="selectExamOption(${index + 1})" aria-pressed="${selectedOption === index + 1}"><span class="option-number">${index + 1}</span><span>${escapeHTML(option)}</span><span class="option-check" aria-hidden="true">${selectedOption === index + 1 ? '✓' : ''}</span></button>`).join('');
    const previousDisabled = examCurrentIndex <= 0;
    const nextLabel = examCurrentIndex + 1 >= examTotal ? 'Завершить экзамен' : 'Далее';
    const content = `<div class="exam-workspace"><div class="exam-topline"><a class="back-link" href="#tests" onclick="navigate('tests'); return false">← Выйти</a><div class="exam-timer"><span class="timer-live-dot"></span><strong id="timerText">${formatTime(examTimeLeft)}</strong><small>осталось</small></div></div><div class="exam-progress-label"><span>${escapeHTML(question.subject || 'Экзамен')}</span><strong>Вопрос ${examCurrentIndex + 1} из ${examTotal}</strong></div><div class="exam-progress-track"><span style="width:${progress}%"></span></div><section class="exam-question-panel"><p class="eyebrow">ВОПРОС ${examCurrentIndex + 1}</p><h1>${escapeHTML(question.text)}</h1><div class="exam-options">${options}</div></section><div class="exam-controls"><button class="action-secondary" type="button" ${previousDisabled ? 'disabled' : ''} onclick="navigateExamQuestion(${examCurrentIndex - 1})">← Назад</button><button class="action-primary" type="button" onclick="${examCurrentIndex + 1 >= examTotal ? 'finishExam()' : `navigateExamQuestion(${examCurrentIndex + 1})`}">${nextLabel} <span aria-hidden="true">→</span></button></div></div>`;
    renderShell('tests', content);
}

async function selectExamOption(selected) {
    const result = await api('POST', '/api/exam/answer', { index: examCurrentIndex, selected });
    if (result.error) {
        if (result.error === 'Stale question') await loadExamQuestion();
        else renderShell('tests', `<div class="empty-state"><h2>Не удалось сохранить ответ</h2><p>${escapeHTML(result.error)}</p><button class="action-secondary" onclick="loadExamQuestion()">Повторить</button></div>`);
        return;
    }
    renderExamQuestion(examCurrentQuestion, result.selected_option ?? selected);
    startExamTimer();
}

async function navigateExamQuestion(index) {
    if (index < 0 || index >= examTotal) return;
    const result = await api('POST', '/api/exam/navigate', { index });
    if (result.expired) return finishExam();
    if (result.error) {
        renderShell('tests', `<div class="empty-state"><h2>Не удалось открыть вопрос</h2><p>${escapeHTML(result.error)}</p><button class="action-secondary" onclick="loadExamQuestion()">Повторить</button></div>`);
        return;
    }
    examCurrentIndex = result.index;
    examCurrentQuestion = result.question;
    examTimeLeft = result.time_remaining;
    renderExamQuestion(result.question, result.selected_option);
    startExamTimer();
}

function startExamTimer() {
    if (examTimer) clearInterval(examTimer);
    examTimer = setInterval(() => {
        examTimeLeft--;
        const el = document.getElementById('timerText');
        if (el) {
            el.textContent = formatTime(examTimeLeft);
            if (examTimeLeft <= 300) el.className = 'timer-text danger';
            else if (examTimeLeft <= 600) el.className = 'timer-text warning';
        }
        if (examTimeLeft <= 0) {
            clearInterval(examTimer);
            examTimer = null;
            finishExam();
        }
    }, 1000);
}

function formatTime(sec) {
    if (sec <= 0) return '00:00';
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    if (m >= 60) {
        const h = Math.floor(m / 60);
        const rm = m % 60;
        return `${h}:${String(rm).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

async function submitExamAnswer(selected, questionId) {
    return selectExamOption(selected);
}

async function finishExam() {
    if (examTimer) { clearInterval(examTimer); examTimer = null; }
    const res = await api('POST', '/api/exam/finish');
    if (res.error) {
        renderShell('tests', `<div class="empty-state"><h2>Не удалось завершить экзамен</h2><p>${escapeHTML(res.error)}</p><button class="action-secondary" onclick="loadExamQuestion()">Вернуться к экзамену</button></div>`);
        return;
    }
    navigate(`exam-result/${res.result_id}`);
}

// --- Exam Result ---
async function renderExamResult(resultId) {
    if (!resultId) return navigate('progress');
    app.innerHTML = '<div class="loading">Загружаем результат...</div>';
    const result = await api('GET', `/api/exam/results/${resultId}`);
    if (result.error) {
        return renderShell('progress', `<div class="empty-state"><h2>Результат не найден</h2><p>Он недоступен этому аккаунту или был удалён.</p><button class="action-secondary" onclick="navigate('progress')">К прогрессу</button></div>`);
    }
    const reviewRows = (result.answers || []).map((answer, index) => {
        const selected = answer.selected_option ? answer.options[answer.selected_option - 1] : 'Нет ответа';
        const correct = answer.options[answer.correct_option - 1] || 'Правильный ответ не указан';
        return `<article class="answer-review-row ${answer.is_correct ? 'answer-correct' : 'answer-wrong'}"><div class="answer-review-head"><span>Вопрос ${index + 1}</span><strong>${answer.is_correct ? 'Верно' : 'Ошибка'}</strong></div><p class="answer-review-question">${escapeHTML(answer.question_text)}</p><div class="answer-review-values"><span>Ваш ответ: <strong>${escapeHTML(selected)}</strong></span><span>Правильный: <strong>${escapeHTML(correct)}</strong></span></div>${answer.explanation ? `<p class="answer-explanation">${escapeHTML(answer.explanation)}</p>` : ''}</article>`;
    }).join('');
    const content = `<section class="page-intro"><p class="eyebrow">РЕЗУЛЬТАТ</p><h1>Экзамен завершён</h1><p>${escapeHTML(result.subject)} · ${result.time_expired ? 'время истекло' : `${Math.floor(result.elapsed_seconds / 60)} мин ${result.elapsed_seconds % 60} сек`}</p></section><section class="result-summary-panel"><div class="result-accuracy" style="--result-score:${result.percentage}%"><span>${result.percentage}%</span></div><div class="result-metrics"><div><strong>${result.score}/${result.max_score}</strong><small>баллы</small></div><div><strong>${result.correct}</strong><small>правильно</small></div><div><strong>${result.errors}</strong><small>ошибки</small></div><div><strong>${result.answered}/${result.total}</strong><small>отвечено</small></div></div></section><section class="dashboard-section"><div class="section-heading"><div><p class="eyebrow">РАЗБОР</p><h2>Ответы по вопросам</h2></div><span class="result-muted">${result.answers.length} ответов</span></div><div class="answer-review-list">${reviewRows || '<div class="empty-state"><h2>Ответов нет</h2><p>Экзамен завершён без сохранённых ответов.</p></div>'}</div></section><div class="detail-actions"><button class="action-primary" onclick="navigate('tests')">Новый тест <span aria-hidden="true">→</span></button><button class="action-secondary" onclick="navigate('progress')">Мой прогресс</button></div>`;
    renderShell('progress', content);
}

// --- Review ---
async function renderReview(index) {
    const res = await api('GET', '/api/review');
    if (res.error) {
        app.innerHTML = `<div class="info-box warning">Нет данных для просмотра</div>
            <button class="btn" onclick="navigate('')">В меню</button>`;
        return;
    }

    const answers = res.answers;
    const total = answers.length;
    if (index < 0) index = 0;
    if (index >= total) index = total - 1;

    const a = answers[index];
    const statusText = a.is_correct ? '✅ Вы ответили правильно' : '❌ Вы ответили неправильно';
    const statusClass = a.is_correct ? 'review-status' : 'review-status';

    let html = `<div class="question-card">`;
    html += `<div class="question-number">Вопрос ${index + 1}/${total}</div>`;
    html += `<div class="${statusClass}" style="color:${a.is_correct ? '#27ae60' : '#e74c3c'}">${statusText}</div>`;
    html += `<div class="question-text">${a.question_text}</div>`;
    html += '<div class="options-list">';
    for (let i = 0; i < a.options.length; i++) {
        const num = i + 1;
        let cls = 'option-btn';
        let suffix = '';
        if (num === a.correct && num === a.selected) {
            cls += ' correct';
            suffix = ' ✅';
        } else if (num === a.correct) {
            cls += ' correct-highlight';
            suffix = ' ← правильный';
        } else if (num === a.selected) {
            cls += ' wrong';
            suffix = ' ← ваш ответ';
        }
        html += `<div class="${cls}"><span class="option-number">${num}.</span> ${a.options[i]}${suffix}</div>`;
    }
    html += '</div>';

    if (a.explanation && a.explanation.trim()) {
        html += `<div class="explanation">💡 ${a.explanation}</div>`;
    }
    html += '</div>';

    // Navigation
    html += '<div class="review-nav">';
    if (index > 0) {
        html += `<button class="btn" onclick="navigate('review/${index - 1}')">⬅️ Назад</button>`;
    }
    if (index < total - 1) {
        html += `<button class="btn" onclick="navigate('review/${index + 1}')">Вперёд ➡️</button>`;
    }
    html += '</div>';
    html += `<div style="margin-top:8px"><button class="btn" onclick="navigate('')">🏠 В меню</button></div>`;
    app.innerHTML = html;
}

// --- Test ---
async function renderTest(subject) {
    testSubject = subject;

    if (!currentTestQ || currentTestQ._subject !== subject) {
        // Start new test
        const res = await api('POST', '/api/test/start', { subject });
        if (res.error) {
            app.innerHTML = `<div class="info-box warning">${res.error}</div>
                <div class="btn-list">
                    <button class="btn btn-primary" onclick="navigate('purchase/${subject}')">💳 Купить доступ</button>
                    <button class="btn" onclick="navigate('')">В меню</button>
                </div>`;
            return;
        }
        currentTestQ = res.question;
        currentTestQ._subject = subject;
        currentTestQ._trialRemaining = res.trial_remaining;
        currentTestQ._hasAccess = res.has_access;
        currentTestQ._answered = false;
    }

    renderTestQuestion();
}

function renderTestQuestion() {
    const q = currentTestQ;
    if (!q) return;

    let html = '';
    if (!q._hasAccess && q._trialRemaining >= 0) {
        html += `<div class="info-box info">🎁 Осталось бесплатных вопросов: ${q._trialRemaining}</div>`;
    }

    html += '<div class="question-card">';
    html += `<div class="question-text">${q.text}</div>`;
    html += '<div class="options-list">';
    for (let i = 0; i < q.options.length; i++) {
        html += `<button class="option-btn" id="opt${i}" onclick="submitTestAnswer(${i + 1}, ${q.id})">
            <span class="option-number">${i + 1}.</span> ${q.options[i]}
        </button>`;
    }
    html += '</div></div>';
    html += '<div id="testFeedback"></div>';
    app.innerHTML = html;
}

async function submitTestAnswer(selected, questionId) {
    // Disable all option buttons
    document.querySelectorAll('.option-btn').forEach(b => b.disabled = true);

    const res = await api('POST', '/api/test/answer', {
        selected,
        question_id: questionId,
    });

    // Highlight correct/wrong
    const options = document.querySelectorAll('.option-btn');
    options.forEach((btn, i) => {
        const num = i + 1;
        if (num === res.correct_option && num === selected) {
            btn.classList.add('correct');
        } else if (num === res.correct_option) {
            btn.classList.add('correct-highlight');
        } else if (num === selected) {
            btn.classList.add('wrong');
        }
    });

    // Feedback
    let fb = '';
    if (res.is_correct) {
        fb += '<div class="feedback-box feedback-correct">✅ Верно!</div>';
    } else {
        fb += `<div class="feedback-box feedback-wrong">❌ Неверно! Правильный ответ: ${res.correct_option}</div>`;
    }

    if (res.explanation && res.explanation.trim()) {
        fb += `<div class="explanation">💡 ${res.explanation}</div>`;
    }

    if (res.trial_limit_reached) {
        fb += `<div class="info-box warning" style="margin-top:12px">⛔ Пробный период закончился</div>`;
        fb += `<div class="btn-list" style="margin-top:8px">
            <button class="btn btn-primary" onclick="navigate('purchase/${testSubject}')">💳 Купить доступ</button>
            <button class="btn" onclick="navigate('')">В меню</button>
        </div>`;
    } else {
        fb += `<div style="margin-top:12px">
            <button class="btn btn-primary" onclick="loadNextTestQuestion()">▶️ Следующий вопрос</button>
        </div>`;
    }

    document.getElementById('testFeedback').innerHTML = fb;
}

async function loadNextTestQuestion() {
    const res = await api('GET', '/api/test/next');
    if (res.error || res.trial_limit_reached) {
        app.innerHTML = `<div class="info-box warning">⛔ ${res.error || 'Пробный период закончился'}</div>
            <div class="btn-list">
                <button class="btn btn-primary" onclick="navigate('purchase/${testSubject}')">💳 Купить доступ</button>
                <button class="btn" onclick="navigate('')">В меню</button>
            </div>`;
        return;
    }

    currentTestQ = res.question;
    currentTestQ._subject = testSubject;
    currentTestQ._trialRemaining = res.trial_remaining;
    currentTestQ._hasAccess = res.has_access;
    renderTestQuestion();
}

// --- Purchase ---
async function renderPurchase(subject) {
    app.innerHTML = `<div class="header"><h1>Доступ к предмету</h1><p>${subject}</p></div>
        <div class="info-box info">Оплата на сайте пока не подключена. Если вы уже покупали доступ в боте, войдите через Telegram. Для нового доступа обратитесь к администратору.</div>
        <div class="btn-list"><button class="btn" onclick="navigate('')">Вернуться в меню</button></div>`;
}

// --- Support ---
async function renderSupport() {
    const data = await api('GET', '/api/support');
    let html = '<div class="header"><h1>📩 Поддержка</h1><p>Напишите сообщение разработчику</p></div>';
    html += '<div class="support-history">';
    for (const ticket of data.tickets || []) {
        html += `<section class="question-card"><div><strong>${escapeHTML(ticket.status)}</strong><span class="row-meta"> · ${escapeHTML(ticket.created_at)}</span></div><p>${escapeHTML(ticket.message)}</p>`;
        for (const reply of ticket.replies || []) html += `<div class="info-box info"><strong>Ответ поддержки</strong><p>${escapeHTML(reply.message)}</p></div>`;
        html += '</section>';
    }
    html += '</div>';
    html += '<textarea class="support-textarea" id="supportMsg" placeholder="Ваше сообщение..."></textarea>';
    html += '<div class="btn-list">';
    html += '<button class="btn btn-primary" id="sendSupportBtn" onclick="sendSupport()">✉️ Отправить</button>';
    html += '</div>';
    app.innerHTML = html;
}

async function sendSupport() {
    const msg = document.getElementById('supportMsg').value.trim();
    if (!msg) return;

    const btn = document.getElementById('sendSupportBtn');
    btn.disabled = true;
    btn.textContent = 'Отправка...';

    const res = await api('POST', '/api/support/send', { message: msg });
    if (res.success) {
        await renderSupport();
        const host = document.createElement('div');
        host.className = 'info-box success';
        host.textContent = 'Сообщение отправлено.';
        app.prepend(host);
    } else {
        btn.disabled = false;
        btn.textContent = '✉️ Отправить';
    }
}

// --- Referral & Balance ---
async function renderReferral() {
    app.innerHTML = '<div class="loading">Загрузка...</div>';
    const d = await api('GET', '/api/referral');
    if (d.error) {
        app.innerHTML = `<div class="info-box warning">${d.error}</div>`;
        return;
    }

    // Прогресс до следующего уровня
    let nextHtml = '';
    if (d.next_level) {
        const pct = Math.round((d.referral_count / (d.referral_count + d.next_level.left)) * 100);
        nextHtml = `
            <div class="ref-progress">
                <div class="ref-progress-label">
                    До уровня ${d.next_level.name}: ещё ${d.next_level.left} покупок
                </div>
                <div class="ref-progress-bar">
                    <div class="ref-progress-fill" style="width:${pct}%"></div>
                </div>
                <div class="ref-progress-hint">бонус вырастет до +${d.next_level.bonus}, лимит до ${d.next_level.limit} сом</div>
            </div>`;
    } else {
        nextHtml = `<div class="info-box success" style="margin:8px 0">🏆 Вы на максимальном уровне!</div>`;
    }

    // История операций
    let historyHtml = '';
    if (d.history.length === 0) {
        historyHtml = '<div class="ref-history-empty">Пока нет операций</div>';
    } else {
        for (const op of d.history) {
            const sign = op.delta > 0 ? '+' : '';
            const cls = op.delta > 0 ? 'ref-op-plus' : 'ref-op-minus';
            const subj = op.subject ? ` (${op.subject})` : '';
            historyHtml += `
                <div class="ref-op-row">
                    <div class="ref-op-info">
                        <div class="ref-op-reason">${op.reason}${subj}</div>
                        <div class="ref-op-date">${op.date}</div>
                    </div>
                    <div class="ref-op-delta ${cls}">${sign}${op.delta}</div>
                </div>`;
        }
    }

    // Реферальная ссылка
    const refLinkHtml = d.ref_link
        ? `<div class="ref-link-box" onclick="copyRefLink('${escapeHTML(d.ref_link)}')">
               <div class="ref-link-text">${d.ref_link}</div>
               <div class="ref-link-copy">📋 Скопировать</div>
           </div>`
        : '';

    app.innerHTML = `
        <div class="header"><h1>💎 Баллы и рефералка</h1></div>

        <div class="ref-balance-card">
            <div class="ref-balance-row">
                <span>💰 Всего баллов</span>
                <span class="ref-balance-val">${d.balance}</span>
            </div>
            <div class="ref-balance-row">
                <span>✅ Доступно</span>
                <span class="ref-balance-val">${d.available} сом</span>
            </div>
            ${d.reserved > 0 ? `<div class="ref-balance-row">
                <span>⏳ Зарезервировано</span>
                <span class="ref-balance-val">${d.reserved}</span>
            </div>` : ''}
            <div class="ref-balance-row">
                <span>🔒 Лимит скидки</span>
                <span class="ref-balance-val">${d.spend_limit} сом</span>
            </div>
        </div>

        <div class="ref-level-card">
            <div class="ref-level-name">${d.level_name}</div>
            <div class="ref-level-stats">
                Приглашено: <b>${d.total_invited}</b> &nbsp;|&nbsp;
                Купили: <b>${d.referral_count}</b> &nbsp;|&nbsp;
                Бонус: <b>+${d.bonus_per_purchase}</b> за покупку
            </div>
            ${nextHtml}
        </div>

        <div class="ref-section-title">🔗 Ваша реферальная ссылка</div>
        ${refLinkHtml}

        <div class="ref-section-title">📋 Последние операции</div>
        <div class="ref-history">${historyHtml}</div>

        <div class="ref-section-title">💡 Как заработать баллы</div>
        <div class="ref-info-box">
            <div>• Зарегистрировался → +5</div>
            <div>• Друг перешёл по ссылке → +10 тебе</div>
            <div>• Ты прошёл 5 вопросов (реферал) → +15</div>
            <div>• Купил предмет → +40</div>
            <div>• Друг купил предмет → +30/40/50 (по уровню)</div>
        </div>
    `;
}

function copyRefLink(link) {
    navigator.clipboard.writeText(link).then(() => {
        window.alert('Ссылка скопирована.');
    }).catch(() => {
        window.alert('Скопируйте ссылку вручную:\n' + link);
    });
}

// ==================== Init ====================
initializeWebClient();
