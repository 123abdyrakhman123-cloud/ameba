const app = document.getElementById('app');

// ==================== State ====================
let CONFIG = null;       // faculties, access, trials
let WEB_CONFIG = null;
let WEB_SESSION = null;
let examTimer = null;    // setInterval ref
let examTimeLeft = 0;    // seconds remaining
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
                <a class="side-link side-support" href="#support">${navIcon('profile')}<span>Поддержка</span></a>
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
        <a class="recent-row" href="#progress"><span class="recent-dot"></span><span><strong>${escapeHTML(item.subject)}</strong><small>${item.correct} из ${item.answered} правильных · ${escapeHTML(item.completed_at.slice(0, 10))}</small></span><span class="recent-score">${item.percentage ?? '—'}%</span></a>`).join('') : '<div class="empty-inline"><strong>История пока пустая</strong><span>Завершите первый экзамен, чтобы увидеть результат здесь.</span></div>';
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
                await renderExamResult();
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
    let html = `<div class="header"><h1>📝 Симуляция экзамена</h1><p>${subject}</p></div>`;
    html += '<div class="question-card">';
    html += '<p>Вы готовы начать экзамен?</p><br>';
    html += '<p>• Количество вопросов: <b>50</b></p>';
    html += '<p>• За правильный ответ: <b>2 балла</b></p>';
    html += '<p>• Время: <b>1 час 15 минут</b></p>';
    html += '</div>';
    html += '<div class="btn-list">';
    html += `<button class="btn btn-primary" id="startExamBtn" onclick="startExam('${subject}')">✅ Да, начать!</button>`;
    html += '</div>';
    app.innerHTML = html;
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

    examTimeLeft = res.time_remaining;
    startExamTimer();

    const q = res.question;
    let html = `<div class="timer-bar">
        <span class="timer-text" id="timerText">${formatTime(examTimeLeft)}</span>
        <span class="timer-progress">Вопрос ${res.question_number}/${res.total}</span>
    </div>`;

    html += '<div class="question-card">';
    html += `<div class="question-text">${q.text}</div>`;
    html += '<div class="options-list">';
    for (let i = 0; i < q.options.length; i++) {
        html += `<button class="option-btn" onclick="submitExamAnswer(${i + 1}, ${q.id})">
            <span class="option-number">${i + 1}.</span> ${q.options[i]}
        </button>`;
    }
    html += '</div></div>';
    app.innerHTML = html;
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
    // Disable buttons
    document.querySelectorAll('.option-btn').forEach(b => b.disabled = true);

    const res = await api('POST', '/api/exam/answer', { selected, question_id: questionId });
    if (res.expired) {
        await finishExam();
        return;
    }
    if (!res.has_next) {
        await finishExam();
        return;
    }
    await loadExamQuestion();
}

async function finishExam() {
    if (examTimer) { clearInterval(examTimer); examTimer = null; }
    const res = await api('POST', '/api/exam/finish');
    // Store result for display
    window._examResult = res;
    navigate('exam-result');
}

// --- Exam Result ---
async function renderExamResult() {
    const res = window._examResult;
    if (!res || res.error) {
        return navigate('');
    }

    const emoji = res.percentage >= 70 ? '🎉' : res.percentage >= 50 ? '📊' : '😔';

    let html = '<div class="result-card">';
    html += `<div style="font-size:40px">${emoji}</div>`;
    html += res.time_expired ? '<h2>Время истекло!</h2>' : '<h2>Экзамен завершён!</h2>';
    html += `<div class="result-score">${res.percentage}%</div>`;
    html += '<div class="result-stats">';
    html += `Баллы: <span>${res.score}/${res.max_score}</span><br>`;
    html += `Отвечено: <span>${res.answered}/${res.total}</span><br>`;
    html += `✅ Правильных: <span>${res.correct}</span>  ❌ Ошибок: <span>${res.errors}</span>`;
    html += '</div></div>';

    html += '<div class="btn-list">';
    html += `<button class="btn btn-primary" onclick="navigate('review/0')">📝 Работа над ошибками</button>`;
    html += `<button class="btn" onclick="navigate('')">🏠 В меню</button>`;
    html += '</div>';
    app.innerHTML = html;
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
