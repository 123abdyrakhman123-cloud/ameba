// ==================== Telegram WebApp ====================
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

const initData = tg.initData;
const app = document.getElementById('app');

// ==================== State ====================
let CONFIG = null;       // faculties, access, trials
let examTimer = null;    // setInterval ref
let examTimeLeft = 0;    // seconds remaining
let currentTestQ = null; // current test question data
let testSubject = null;

// ==================== API Helper ====================
async function api(method, path, body = null) {
    const opts = {
        method,
        headers: {
            'Authorization': initData,
            'Content-Type': 'application/json',
        },
    };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
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
    window.location.hash = hash;
}

function getRoute() {
    const hash = window.location.hash.slice(1) || '';
    const parts = hash.split('/');
    return { path: parts[0] || '', params: parts.slice(1) };
}

window.addEventListener('hashchange', route);

// Back button
tg.BackButton.onClick(() => {
    const { path, params } = getRoute();
    if (path === 'courses') navigate('');
    else if (path === 'subjects') navigate('courses/' + params[0]);
    else if (path === 'modes') navigate('subjects/' + params[0] + '/' + params[1]);
    else if (path === 'exam-start') navigate('modes/' + params.join('/'));
    else if (path === 'test') navigate('modes/' + params.join('/'));
    else if (path === 'purchase') navigate('modes/' + params.join('/'));
    else if (path === 'exam-result' || path === 'review') navigate('');
    else if (path === 'support') navigate('');
    else navigate('');
});

async function route() {
    const { path, params } = getRoute();

    // Show/hide back button
    if (path === '') {
        tg.BackButton.hide();
    } else {
        tg.BackButton.show();
    }

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
            default:
                navigate('');
        }
    } catch (e) {
        console.error(e);
        app.innerHTML = '<div class="loading">Ошибка загрузки. Попробуйте снова.</div>';
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

    // Purchase
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
                <button class="btn btn-primary" onclick="tg.close()">⬇️ Закрыть приложение</button>
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

// ==================== Init ====================
route();
