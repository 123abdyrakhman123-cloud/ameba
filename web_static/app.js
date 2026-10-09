const app = document.getElementById('app');

// ==================== State ====================
let CONFIG = null;       // faculties, access, trials
let WEB_CONFIG = null;
let WEB_SESSION = null;
let examTimer = null;    // setInterval ref
let examTimeLeft = 0;    // seconds remaining
let currentTestQ = null; // current test question data
let testSubject = null;

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
                await renderFaculties();
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
                navigate('');
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
                else return api('GET', '/api/session').then(session => {
                    WEB_SESSION = session.authenticated ? session : null;
                    if (WEB_SESSION) route();
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
        if (WEB_SESSION) route();
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
    let html = '<div class="header"><h1>AMEBA</h1><p>Подготовка к экзаменам</p></div>';
    html += '<div class="btn-list">';
    for (const [key, fac] of Object.entries(cfg.faculties)) {
        html += `<button class="btn" onclick="navigate('courses/${key}')">${fac.name}</button>`;
    }
    html += `<button class="btn" onclick="navigate('referral')">💎 Баллы и рефералка</button>`;
    html += `<button class="btn" onclick="navigate('support')">📩 Поддержка</button>`;
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
            💳 Купить доступ
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
    let html = `<div class="header"><h1>💳 Покупка доступа</h1><p>${subject}</p></div>`;
    html += '<div class="btn-list">';

    const prices = [
        { period: 'forever', label: 'Навсегда', price: '300с' },
    ];

    for (const p of prices) {
        html += `<button class="btn" onclick="selectPurchase('${subject}', '${p.period}')">
            ${p.label} <span class="price-tag">${p.price}</span>
        </button>`;
    }
    html += '</div>';

    html += '<div class="info-box info" style="margin-top:16px">';
    html += '📎 После оплаты отправьте квитанцию администратору бота @Ameba_admin или через поддержку.';
    html += '</div>';
    html += `<div style="margin-top:8px"><button class="btn" onclick="navigate('support')">📩 Отправить квитанцию</button></div>`;
    app.innerHTML = html;
}

async function selectPurchase(subject, period) {
    const btn = event && event.target;
    if (btn) { btn.disabled = true; btn.textContent = 'Загрузка...'; }
    let res;
    try {
        res = await api('POST', '/api/purchase/select', { subject, period });
    } catch (e) {
        app.innerHTML = `<div class="info-box warning">Ошибка соединения. Попробуйте позже.</div>
            <button class="btn" onclick="navigate('purchase/${subject}')">🔄 Повторить</button>`;
        return;
    }
    if (res.error) {
        app.innerHTML = `<div class="info-box warning">${res.error}</div>
            <button class="btn" onclick="navigate('purchase/${subject}')">🔄 Повторить</button>`;
        return;
    }
    if (res.success) {
        let qrHtml = "";
        if (res.qr_url) {
            qrHtml = `<img src="${res.qr_url}" style="width: 100%; border-radius: 8px; margin: 10px 0;">`;
        }
        
        app.innerHTML = `
            <div class="info-box success">
                ✅ Инструкция по оплате и QR-код готовы!
            </div>
            <div class="question-card" style="text-align: center;">
                <p>Отсканируйте QR-код для оплаты:</p>
                ${qrHtml}
                <br>
                <p>• Сохраните фото или оплатите сейчас</p>
                <p>• Затем закройте приложение и отправьте чек прямо боту!</p>
                <p>Обязательно нажмите "Я оплатил" в чате с ботом.</p>
            </div>
            <div class="btn-list">
                <button class="btn btn-primary" onclick="navigate('')">Вернуться в меню</button>
            </div>`;
    }
}

// --- Support ---
async function renderSupport() {
    let html = '<div class="header"><h1>📩 Поддержка</h1><p>Напишите сообщение разработчику</p></div>';
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
        app.innerHTML = `
            <div class="info-box success">✅ Сообщение отправлено!</div>
            <button class="btn" onclick="navigate('')">🏠 В меню</button>`;
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
        ? `<div class="ref-link-box" onclick="copyRefLink('${d.ref_link}')">
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
