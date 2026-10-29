/* ТГУ: Навигатор возможностей — логика MVP-фронтенда.
 *
 * Общается с FastAPI-бэкендом:
 *   POST /ask  {query} -> {found, intro, cards[], next_step, sources[]}
 *   GET  /opportunities/{id} -> полная карточка для модального окна.
 *
 * Адрес API берётся из window.API_BASE (можно переопределить, добавив
 * <script>window.API_BASE="http://..."</script> до app.js), по умолчанию —
 * тот же хост, что отдаёт страницу (фронтенд раздаётся самим FastAPI).
 */

"use strict";

const API_BASE = (window.API_BASE || "").replace(/\/+$/, "");

/** Эмодзи и названия типов возможностей. */
const TYPE_META = {
  project: { icon: "🔬", label: "Проект" },
  lab: { icon: "🏛️", label: "Лаборатория" },
  event: { icon: "📅", label: "Мероприятие" },
  grant: { icon: "💰", label: "Грант" },
};

/** Готовые формулировки для кнопок «Быстрые запросы» и подсказок. */
const PRESETS = {
  projects: "Хочу попасть в научный проект по искусственному интеллекту",
  grants: "Какие гранты и стипендии доступны студентам?",
  events: "Ближайшие хакатоны и мероприятия",
  labs: "Интересуют лаборатории с направлениями NLP и анализ данных",
  custom: "Интересуюсь ИИ и хочу попасть в реальный проект",
};

// --- Состояние -------------------------------------------------------------

let queryCount = 0;
let cardCount = 0;
let busy = false;

const els = {
  chatArea: document.getElementById("chatArea"),
  welcome: document.getElementById("welcomeScreen"),
  input: document.getElementById("userInput"),
  sendBtn: document.getElementById("sendBtn"),
  statQueries: document.getElementById("statQueries"),
  statCards: document.getElementById("statCards"),
  modalOverlay: document.getElementById("modalOverlay"),
  modalBox: document.getElementById("modalBox"),
  modalClose: document.getElementById("modalClose"),
  modalContent: document.getElementById("modalContent"),
  toast: document.getElementById("toast"),
  flowSteps: [
    document.getElementById("fs1"),
    document.getElementById("fs2"),
    document.getElementById("fs3"),
    document.getElementById("fs4"),
  ],
  flowLines: [
    document.getElementById("fl1"),
    document.getElementById("fl2"),
    document.getElementById("fl3"),
  ],
};

// --- Утилиты ---------------------------------------------------------------

/** Экранирует текст для безопасной вставки в HTML. */
function esc(text) {
  const div = document.createElement("div");
  div.textContent = String(text ?? "");
  return div.innerHTML;
}

/** Показывает всплывающее уведомление внизу экрана. */
function showToast(message, isError = false) {
  els.toast.textContent = message;
  els.toast.classList.toggle("error", isError);
  els.toast.classList.add("show");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => els.toast.classList.remove("show"), 3500);
}

/** Обновляет счётчики статистики пилота. */
function updateStats() {
  els.statQueries.textContent = String(queryCount);
  els.statCards.textContent = String(cardCount);
}

/** Переключает индикатор процесса: Запрос → Поиск → Рекомендации → Действие. */
function setFlow(stage) {
  // stage: 1..4 — активный шаг; шаги до него помечаются выполненными.
  els.flowSteps.forEach((step, i) => {
    step.classList.toggle("done", i + 1 < stage);
    step.classList.toggle("active", i + 1 === stage);
  });
  els.flowLines.forEach((line, i) => {
    line.classList.toggle("done", i + 1 < stage);
  });
}

// --- Сообщения чата ---------------------------------------------------------

/** Добавляет сообщение пользователя справа. */
function addUserMessage(text) {
  if (els.welcome) {
    els.welcome.remove();
    els.welcome = null;
  }
  const msg = document.createElement("div");
  msg.className = "msg user";
  msg.innerHTML = `<div class="bubble">${esc(text)}</div>`;
  els.chatArea.appendChild(msg);
  scrollBottom();
}

/** Добавляет «пузырь» ассистента и возвращает элемент для наполнения. */
function addBotBubble() {
  const msg = document.createElement("div");
  msg.className = "msg bot";
  msg.innerHTML = `<div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div>`;
  els.chatArea.appendChild(msg);
  scrollBottom();
  return msg.querySelector(".bubble");
}

function scrollBottom() {
  els.chatArea.scrollTop = els.chatArea.scrollHeight;
}

/** Рендерит ответ /ask внутри пузыря ассистента. */
function renderAnswer(bubble, data) {
  const parts = [];
  parts.push(`<div class="intro">${esc(data.intro || "")}</div>`);

  if (data.cards && data.cards.length) {
    const cards = data.cards.map((c) => {
      const meta = TYPE_META[c.type] || { icon: "✨", label: c.type };
      const soon = c.status === "closing_soon";
      const deadline = c.deadline
        ? `<span class="deadline${soon ? " soon" : ""}">⏳ до ${esc(c.deadline)}${soon ? " · скоро закрытие" : ""}</span>`
        : "";
      const contact = c.contact ? `<span>📞 ${esc(c.contact)}</span>` : "";
      return `
        <div class="card">
          <div class="card-head">
            <span class="card-type">${meta.icon}</span>
            <span class="card-title">${esc(c.title)}</span>
          </div>
          <div class="card-summary">${esc(c.summary)}</div>
          <div class="card-meta">${deadline}${contact}</div>
          <div class="card-actions">
            <button class="btn" data-details="${c.id}">Подробнее</button>
            <a class="btn primary" href="${esc(c.source_url)}" target="_blank" rel="noopener">Источник ↗</a>
          </div>
        </div>`;
    }).join("");
    parts.push(`<div class="cards">${cards}</div>`);
  }

  if (data.next_step) {
    parts.push(`<div class="next-step">${esc(data.next_step)}</div>`);
  }

  bubble.innerHTML = parts.join("");
  scrollBottom();
}

// --- Модалка «Подробнее» -----------------------------------------------------

async function openDetails(id) {
  try {
    const resp = await fetch(`${API_BASE}/opportunities/${id}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const o = await resp.json();
    const meta = TYPE_META[o.type] || { icon: "✨", label: o.type };
    const field = (title, value) =>
      value ? `<div class="modal-field"><h4>${title}</h4><p>${esc(value)}</p></div>` : "";
    els.modalContent.innerHTML = `
      <h2>${meta.icon} ${esc(o.title)}</h2>
      <div class="modal-type">${esc(meta.label)} · статус: ${esc(o.status)}</div>
      ${field("Описание", o.description)}
      ${field("Требования", o.requirements)}
      ${field("Для кого", o.audience)}
      ${field("Теги", (o.tags || []).join(", "))}
      ${field("Срок подачи", o.deadline)}
      ${field("Контакт", o.contact)}
      <div class="modal-footer">
        <a class="btn primary" href="${esc(o.source_url)}" target="_blank" rel="noopener">Официальный источник ↗</a>
      </div>`;
    els.modalOverlay.classList.add("open");
  } catch (err) {
    showToast("Не удалось загрузить карточку: " + err.message, true);
  }
}

function hideModal() {
  els.modalOverlay.classList.remove("open");
}

// --- Основной сценарий -------------------------------------------------------

async function sendMessage(rawText) {
  const text = (rawText ?? els.input.value).trim();
  if (!text || busy) return;

  busy = true;
  els.sendBtn.disabled = true;
  els.input.value = "";

  addUserMessage(text);
  queryCount += 1;
  updateStats();
  setFlow(1);

  const bubble = addBotBubble();

  // Шаг «Поиск»: имитируем последовательность стадий без sleep-задержек
  // сверх времени самого запроса — переходы привязаны к событиям ответа.
  setFlow(2);

  try {
    const resp = await fetch(`${API_BASE}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: text }),
    });
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try {
        const body = await resp.json();
        if (body && body.detail) detail = JSON.stringify(body.detail);
      } catch (_) { /* тело может быть не-JSON */ }
      throw new Error(detail);
    }
    const data = await resp.json();
    setFlow(3);
    cardCount += (data.cards || []).length;
    updateStats();
    renderAnswer(bubble, data);
    setFlow(4);
  } catch (err) {
    bubble.innerHTML =
      `<div class="intro">Не удалось получить ответ от сервера 😔</div>` +
      `<div class="next-step">${esc(err.message)}. Проверь, что бэкенд запущен.</div>`;
    showToast("Ошибка соединения с API", true);
    setFlow(1);
  } finally {
    busy = false;
    els.sendBtn.disabled = false;
    els.input.focus();
  }
}

// --- Инициализация -----------------------------------------------------------

function init() {
  els.sendBtn.addEventListener("click", () => sendMessage());
  els.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") sendMessage();
  });

  // Пресеты: боковые кнопки и чипы-подсказки.
  document.querySelectorAll("[data-preset]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.getAttribute("data-preset");
      const presetText = PRESETS[key];
      if (presetText) sendMessage(presetText);
    });
  });

  // Кнопки «Подробнее» внутри карточек (делегирование событий).
  els.chatArea.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-details]");
    if (btn) openDetails(Number(btn.getAttribute("data-details")));
  });

  // Модалка: закрытие по крестику, клику на фон и Escape.
  els.modalClose.addEventListener("click", hideModal);
  els.modalOverlay.addEventListener("click", (event) => {
    if (event.target === els.modalOverlay) hideModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideModal();
  });

  els.input.focus();
}

document.addEventListener("DOMContentLoaded", init);
