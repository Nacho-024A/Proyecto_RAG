/* ===== Nexora — interfaz =====
   Toda la comunicación con el servidor pasa por el objeto `api`.
   MOCK = true  -> funciona sola (datos de prueba en localStorage), sin servidor.
   MOCK = false -> usa el backend FastAPI (rutas /api/...), ver realApi más abajo. */
(() => {
  'use strict';

  const MOCK = false;
  const MAX_BYTES = 200 * 1024 * 1024;

  /* ---------------------------------------------------------------- */
  /* Capa de datos                                                    */
  /* ---------------------------------------------------------------- */
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  // --- Simulada: sirve para probar el diseño sin backend
  const STORE_KEY = 'nexora_mock_chats_v1';
  const loadStore = () => { try { return JSON.parse(localStorage.getItem(STORE_KEY)) || []; } catch (e) { return []; } };
  const saveStore = (chats) => { try { localStorage.setItem(STORE_KEY, JSON.stringify(chats)); } catch (e) { /* sin almacenamiento */ } };

  async function countPdfPages(file) {
    if (file.size > 30 * 1024 * 1024) return 75;
    try {
      const txt = await file.text();
      const n = (txt.match(/\/Type\s*\/Page(?![s\w])/g) || []).length;
      return n || 75;
    } catch (e) { return 75; }
  }

  function mockPageUrl(chat, n) {
    const svg =
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 425 642">' +
      '<rect width="425" height="642" fill="#fff"/>' +
      '<g font-family="Open Sans, Arial, sans-serif" text-anchor="middle" fill="#000">' +
      '<text x="212" y="270" font-size="40">SIMULACION</text>' +
      '<text x="212" y="322" font-size="40">DE</text>' +
      '<text x="212" y="374" font-size="40">DOCUMENTO</text>' +
      '<text x="212" y="440" font-size="18" fill="#555">Página ' + n + ' de ' + chat.n_pages + '</text>' +
      '</g></svg>';
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  }

  const mockApi = {
    async list() { return loadStore().map(({ id, name, n_pages }) => ({ id, name, n_pages })); },
    async upload(file) {
      await wait(1200);
      const n_pages = await countPdfPages(file);
      const chat = { id: 'c' + Date.now().toString(36), name: file.name, n_pages, n_chunks: n_pages * 3, messages: [] };
      const all = loadStore(); all.unshift(chat); saveStore(all);
      return chat;
    },
    async get(id) {
      const chat = loadStore().find((c) => c.id === id);
      if (!chat) throw new Error('No se encontró el chat.');
      return chat;
    },
    async ask(id, question) {
      await wait(900 + Math.random() * 600);
      const all = loadStore();
      const chat = all.find((c) => c.id === id);
      if (!chat) throw new Error('No se encontró el chat.');
      const a = 1 + Math.floor(Math.random() * chat.n_pages);
      const b = 1 + Math.floor(Math.random() * chat.n_pages);
      const pages = a === b ? [a] : [a, b];
      const answer = 'Esta es una respuesta de prueba a «' + question + '». ' +
        'Cuando el backend esté conectado, aquí aparecerá la respuesta del documento [Pág. ' + pages[0] + ']' +
        (pages[1] ? ' y lo que se amplía en otra sección [Pág. ' + pages[1] + '].' : '.');
      chat.messages.push({ role: 'user', text: question, pages: [] });
      chat.messages.push({ role: 'assistant', text: answer, pages });
      saveStore(all);
      return { answer, pages };
    },
    async remove(id) { saveStore(loadStore().filter((c) => c.id !== id)); },
    pageUrl: mockPageUrl,
  };

  async function json(res) {
    if (!res.ok) {
      let detail;
      try { const d = (await res.json()).detail; detail = typeof d === 'string' ? d : null; } catch (e) { /* sin cuerpo */ }
      throw new Error(detail || 'Error ' + res.status);
    }
    return res.json();
  }
  const realApi = {
    list: () => fetch('/api/chats').then(json),
    upload: (file) => { const fd = new FormData(); fd.append('file', file); return fetch('/api/chats', { method: 'POST', body: fd }).then(json); },
    get: (id) => fetch('/api/chats/' + id).then(json),
    ask: (id, question) => fetch('/api/chats/' + id + '/ask', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question }),
    }).then(json),
    remove: (id) => fetch('/api/chats/' + id, { method: 'DELETE' }).then(json),
    pageUrl: (chat, n) => '/api/chats/' + chat.id + '/pages/' + n + '.png',
    pdfUrl: (chat) => '/api/chats/' + chat.id + '/file',
  };

  const api = MOCK ? mockApi : realApi;

  /* ---------------------------------------------------------------- */
  /* Utilidades de DOM                                                */
  /* ---------------------------------------------------------------- */
  const $ = (sel) => document.querySelector(sel);
  const SVG_NS = 'http://www.w3.org/2000/svg';
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function icon(id) {
    const s = document.createElementNS(SVG_NS, 'svg');
    s.setAttribute('class', 'i');
    s.setAttribute('aria-hidden', 'true');
    const u = document.createElementNS(SVG_NS, 'use');
    u.setAttribute('href', '#' + id);
    s.appendChild(u);
    return s;
  }

  const els = {
    home: $('#home'), chatView: $('#chat-view'),
    upload: $('#upload'), file: $('#file'), uploadLabel: $('#upload-label'), uploadHint: $('#upload-hint'), uploadMsg: $('#upload-msg'),
    messages: $('#messages'), question: $('#question'), send: $('#send'),
    pageImg: $('#page-img'), pageInput: $('#page-input'), total: $('#total'), prev: $('#prev'), next: $('#next'),
    docScroll: $('#doc-scroll'), pdfPage: $('#pdf-page'), pdfCanvas: $('#pdf-canvas'), textLayer: $('#text-layer'),
    docStatus: $('#doc-status'), zoom: $('#zoom'), zoomIn: $('#zoom-in'), zoomOut: $('#zoom-out'), zoomReset: $('#zoom-reset'),
    toggle: $('#toggle'), sidebar: $('#sidebar'), scrim: $('#scrim'), newChat: $('#new-chat'), history: $('#history'),
    confirm: $('#confirm'), confirmName: $('#confirm-name'), toast: $('#toast'),
  };

  const state = { list: [], chat: null, page: 1, busy: false };

  /* ---------------------------------------------------------------- */
  /* Aviso (toast)                                                    */
  /* ---------------------------------------------------------------- */
  let toastTimer;
  function toast(msg) {
    els.toast.textContent = msg;
    els.toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => els.toast.classList.remove('show'), 2200);
  }

  /* ---------------------------------------------------------------- */
  /* Barra lateral                                                    */
  /* ---------------------------------------------------------------- */
  function isSidebarOpen() { return document.body.classList.contains('sidebar-open'); }
  function setSidebar(open, restoreFocus) {
    document.body.classList.toggle('sidebar-open', open);
    els.sidebar.inert = !open;
    els.toggle.setAttribute('aria-expanded', String(open));
    els.toggle.setAttribute('aria-label', open ? 'Cerrar historial de chats' : 'Abrir historial de chats');
    if (open) els.newChat.focus();
    else if (restoreFocus) els.toggle.focus();
  }
  function syncToggleVisibility() {
    els.toggle.hidden = !state.chat && state.list.length === 0;
  }

  function renderSidebar() {
    els.history.replaceChildren();
    if (state.list.length === 0) {
      els.history.appendChild(el('li', 'history-empty', 'Aún no hay chats. Sube un PDF para empezar.'));
      return;
    }
    for (const c of state.list) {
      const li = el('li', 'history-item');
      const open = el('button', 'history-open');
      open.type = 'button';
      open.appendChild(el('span', 'history-name', c.name));
      if (state.chat && state.chat.id === c.id) open.setAttribute('aria-current', 'true');
      open.addEventListener('click', () => { setSidebar(false); openChat(c.id); });

      const del = el('button', 'history-del');
      del.type = 'button';
      del.setAttribute('aria-label', 'Eliminar chat: ' + c.name);
      del.appendChild(icon('i-trash'));
      del.addEventListener('click', (e) => { e.stopPropagation(); askDelete(c); });

      li.append(open, del);
      els.history.appendChild(li);
    }
  }

  /* ---------------------------------------------------------------- */
  /* Borrado con confirmación                                         */
  /* ---------------------------------------------------------------- */
  let pendingDelete = null;
  function askDelete(chat) {
    pendingDelete = chat;
    els.confirmName.textContent = chat.name;
    els.confirm.showModal();
  }
  els.confirm.addEventListener('click', (e) => { if (e.target === els.confirm) els.confirm.close('cancel'); });
  els.confirm.addEventListener('close', async () => {
    const target = pendingDelete;
    const confirmed = els.confirm.returnValue === 'delete';
    pendingDelete = null;
    els.confirm.returnValue = '';
    if (!confirmed || !target) return;
    try {
      await api.remove(target.id);
      await refreshList();
      if (state.chat && state.chat.id === target.id) showHome();
      else renderSidebar();
      toast('Chat eliminado');
    } catch (e) {
      toast('No se pudo eliminar: ' + e.message);
    }
  });

  /* ---------------------------------------------------------------- */
  /* Vistas                                                           */
  /* ---------------------------------------------------------------- */
  async function refreshList() {
    try { state.list = await api.list(); } catch (e) { state.list = []; }
    syncToggleVisibility();
  }

  function showHome() {
    state.chat = null;
    releaseDocument();
    els.home.hidden = false;
    els.chatView.hidden = true;
    setUploadMessage('');
    renderSidebar();
    syncToggleVisibility();
  }

  async function openChat(id) {
    try {
      const chat = await api.get(id);
      state.chat = chat;
      state.page = 1;
      els.home.hidden = true;
      els.chatView.hidden = false;
      renderMessages();
      renderControls();
      loadDocument(chat);
      renderSidebar();
      syncToggleVisibility();
      els.question.focus();
    } catch (e) {
      toast(e.message);
    }
  }

  /* ---------------------------------------------------------------- */
  /* Subida de documentos                                             */
  /* ---------------------------------------------------------------- */
  function setUploadMessage(msg, isError) {
    els.uploadMsg.textContent = msg;
    els.uploadMsg.classList.toggle('is-error', !!isError);
  }
  function setUploading(on) {
    els.upload.classList.toggle('is-busy', on);
    els.file.disabled = on;
    els.uploadLabel.textContent = on ? 'Procesando…' : 'Upload';
    els.uploadHint.textContent = on ? 'Leyendo el documento' : '200MB per file - PDF';
  }

  async function handleFile(file) {
    if (!file) return;
    const isPdf = file.type === 'application/pdf' || /\.pdf$/i.test(file.name);
    if (!isPdf) return setUploadMessage('Solo se aceptan archivos PDF.', true);
    if (file.size > MAX_BYTES) return setUploadMessage('El archivo supera los 200 MB.', true);

    setUploadMessage('');
    setUploading(true);
    try {
      const chat = await api.upload(file);
      await refreshList();
      await openChat(chat.id);
    } catch (e) {
      setUploadMessage(e.message || 'No se pudo procesar el documento.', true);
    } finally {
      setUploading(false);
      els.file.value = '';
    }
  }

  els.file.addEventListener('change', () => handleFile(els.file.files[0]));
  ['dragenter', 'dragover'].forEach((t) => els.upload.addEventListener(t, (e) => { e.preventDefault(); els.upload.classList.add('is-drag'); }));
  ['dragleave', 'drop'].forEach((t) => els.upload.addEventListener(t, () => els.upload.classList.remove('is-drag')));
  els.upload.addEventListener('drop', (e) => { e.preventDefault(); handleFile(e.dataTransfer.files[0]); });
  // evita que el navegador abra el PDF si se suelta fuera de la barra
  ['dragover', 'drop'].forEach((t) => window.addEventListener(t, (e) => e.preventDefault()));

  /* ---------------------------------------------------------------- */
  /* Visor de páginas                                                 */
  /* ---------------------------------------------------------------- */
  function goto(n) {
    const total = state.chat.n_pages;
    n = Math.round(Number(n));
    if (!Number.isFinite(n)) n = state.page;
    state.page = Math.max(1, Math.min(total, n));
    renderDoc();
  }
  /* PDF real con pdf.js: texto seleccionable y zoom.
     Si pdf.js no carga o falla, se usa la imagen PNG de la página como respaldo. */
  const pdfjs = window.pdfjsLib;
  if (pdfjs) pdfjs.GlobalWorkerOptions.workerSrc = 'vendor/pdfjs/pdf.worker.min.js';
  const canUsePdfJs = () => !!pdfjs && typeof api.pdfUrl === 'function';

  const ZOOM_MIN = 0.5, ZOOM_MAX = 4;
  const view = { doc: null, mode: 'pdf', zoom: 1, token: 0, loadId: 0, task: null, textTask: null, lastPage: 0, timer: null };

  function setDocMode(mode) {
    view.mode = mode;
    els.docScroll.hidden = mode !== 'pdf';
    els.zoom.hidden = mode !== 'pdf';
    els.pageImg.hidden = mode !== 'img';
  }
  function setDocStatus(msg) {
    els.docStatus.hidden = !msg;
    els.docStatus.textContent = msg || '';
  }
  function updateZoomUi() {
    els.zoomReset.textContent = Math.round(view.zoom * 100) + '%';
    els.zoomOut.disabled = view.zoom <= ZOOM_MIN + 1e-6;
    els.zoomIn.disabled = view.zoom >= ZOOM_MAX - 1e-6;
  }
  function cancelRender() {
    for (const k of ['task', 'textTask']) {
      if (view[k]) { try { view[k].cancel(); } catch (e) { /* ya terminó */ } view[k] = null; }
    }
  }
  function releaseDocument() {
    view.loadId++;
    view.token++;
    clearTimeout(view.timer);
    cancelRender();
    if (view.doc) { Promise.resolve(view.doc.destroy()).catch(() => {}); view.doc = null; }
  }

  async function loadDocument(chat) {
    releaseDocument();
    view.zoom = 1;
    view.lastPage = 0;
    updateZoomUi();
    els.pageImg.removeAttribute('src');
    if (!canUsePdfJs()) { setDocMode('img'); drawPage(); return; }
    setDocMode('pdf');
    setDocStatus('Cargando documento…');
    const id = view.loadId;
    try {
      const doc = await pdfjs.getDocument({ url: api.pdfUrl(chat), standardFontDataUrl: 'vendor/pdfjs/standard_fonts/' }).promise;
      if (id !== view.loadId) { doc.destroy(); return; }
      view.doc = doc;
      setDocStatus('');
      drawPage();
    } catch (e) {
      if (id !== view.loadId) return;
      console.error('pdf.js no pudo abrir el documento; se usa la imagen de cada página.', e);
      setDocStatus('');
      setDocMode('img');
      drawPage();
    }
  }

  async function renderPdfPage() {
    const doc = view.doc;
    if (!doc) return;
    const token = ++view.token;
    cancelRender();
    try {
      const page = await doc.getPage(state.page);
      if (token !== view.token) return;

      // "100%" = la página completa a la vista; el zoom parte de ahí
      const base = page.getViewport({ scale: 1 });
      const fit = Math.min(Math.max(els.docScroll.clientWidth, 50) / base.width, Math.max(els.docScroll.clientHeight, 50) / base.height);
      const viewport = page.getViewport({ scale: fit * view.zoom });

      let dpr = window.devicePixelRatio || 1;
      const maxPixels = 16e6; // evita canvas gigantes con zoom alto
      if (viewport.width * viewport.height * dpr * dpr > maxPixels) dpr = Math.sqrt(maxPixels / (viewport.width * viewport.height));

      const w = Math.floor(viewport.width), h = Math.floor(viewport.height);
      els.pdfPage.style.width = w + 'px';
      els.pdfPage.style.height = h + 'px';
      els.pdfCanvas.width = Math.floor(viewport.width * dpr);
      els.pdfCanvas.height = Math.floor(viewport.height * dpr);
      els.pdfCanvas.style.width = w + 'px';
      els.pdfCanvas.style.height = h + 'px';
      els.textLayer.replaceChildren();
      els.textLayer.style.setProperty('--scale-factor', String(viewport.scale));

      view.task = page.render({
        canvasContext: els.pdfCanvas.getContext('2d'),
        viewport,
        transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null,
      });
      await view.task.promise;
      if (token !== view.token) return;

      if (view.lastPage !== state.page) { els.docScroll.scrollTop = 0; els.docScroll.scrollLeft = 0; view.lastPage = state.page; }

      const content = await page.getTextContent();
      if (token !== view.token) return;
      view.textTask = pdfjs.renderTextLayer({ textContentSource: content, container: els.textLayer, viewport, textDivs: [] });
      await view.textTask.promise;
    } catch (e) {
      if (token !== view.token || (e && e.name === 'RenderingCancelledException')) return;
      console.error('Error al dibujar la página; se usa la imagen de respaldo.', e);
      setDocMode('img');
      drawPage();
    }
  }

  function drawPage() {
    if (!state.chat) return;
    if (view.mode === 'img') {
      els.pageImg.classList.remove('is-error');
      els.pageImg.alt = 'Página ' + state.page + ' de ' + state.chat.n_pages + ' de ' + state.chat.name;
      els.pageImg.src = api.pageUrl(state.chat, state.page);
    } else if (view.doc) {
      renderPdfPage();
    }
  }

  function setZoom(z, delayed) {
    view.zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.round(z * 100) / 100));
    updateZoomUi();
    clearTimeout(view.timer);
    if (delayed) view.timer = setTimeout(drawPage, 120); else drawPage();
  }

  function renderControls() { // Actualiza los controles de navegación de páginas
    const chat = state.chat;
    els.pageInput.max = String(chat.n_pages);
    els.pageInput.value = String(state.page);
    els.total.textContent = '/ ' + chat.n_pages;
    els.prev.disabled = state.page <= 1;
    els.next.disabled = state.page >= chat.n_pages;
  }
  function renderDoc() { renderControls(); drawPage(); } // Funcion que se llama cada vez que cambia la página, para actualizar controles y dibujar la página

  els.pageImg.addEventListener('error', () => els.pageImg.classList.add('is-error'));
  els.zoomIn.addEventListener('click', () => setZoom(view.zoom + 0.25));
  els.zoomOut.addEventListener('click', () => setZoom(view.zoom - 0.25));
  els.zoomReset.addEventListener('click', () => setZoom(1));
  // Ctrl + rueda del mouse = zoom
  els.docScroll.addEventListener('wheel', (e) => {
    if (!e.ctrlKey || view.mode !== 'pdf') return;
    e.preventDefault();
    setZoom(view.zoom * (e.deltaY < 0 ? 1.1 : 1 / 1.1), true);
  }, { passive: false });
  els.docScroll.addEventListener('keydown', (e) => {
    if (e.key === '+' || e.key === '=') { e.preventDefault(); setZoom(view.zoom + 0.25); }
    else if (e.key === '-') { e.preventDefault(); setZoom(view.zoom - 0.25); }
    else if (e.key === '0') { e.preventDefault(); setZoom(1); }
  });
  // al cambiar el tamaño de la ventana, se vuelve a ajustar la página
  let resizeTimer;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (state.chat && view.mode === 'pdf') drawPage(); }, 200);
  });
  els.prev.addEventListener('click', () => goto(state.page - 1));
  els.next.addEventListener('click', () => goto(state.page + 1));
  els.pageInput.addEventListener('change', () => goto(els.pageInput.value));
  els.pageInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { goto(els.pageInput.value); els.pageInput.blur(); } });

  /* ---------------------------------------------------------------- */
  /* Chat                                                             */
  /* ---------------------------------------------------------------- */
  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      const ta = el('textarea');
      ta.value = text;
      ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
  }

  // Convierte "[Pág. 12]" dentro del texto en botones que abren esa página.
  function fillText(container, text) {
    const found = new Set();
    const re = /\[P[áa]g\.?\s*(\d+)\]/g;
    let last = 0, m;
    while ((m = re.exec(text)) !== null) {
      container.appendChild(document.createTextNode(text.slice(last, m.index)));
      const n = Number(m[1]);
      found.add(n);
      const b = el('button', 'ref', 'Pág. ' + n);
      b.type = 'button';
      b.addEventListener('click', () => goto(n));
      container.appendChild(b);
      last = re.lastIndex;
    }
    container.appendChild(document.createTextNode(text.slice(last)));
    return found;
  }

  function buildMessage(m) {
    if (m.role === 'user') {
      const b = el('div', 'msg msg-user');
      b.appendChild(el('div', 'msg-text', m.text));
      return b;
    }
    const b = el('div', 'msg msg-bot' + (m.error ? ' msg-error' : ''));
    const body = el('div', 'msg-text');
    const inline = fillText(body, m.text);
    b.appendChild(body);

    const extra = (m.pages || []).filter((p) => !inline.has(p));
    if (!m.error && (extra.length || m.text)) {
      const actions = el('div', 'msg-actions');
      for (const p of extra) {
        const r = el('button', 'ref', 'Pág. ' + p);
        r.type = 'button';
        r.addEventListener('click', () => goto(p));
        actions.appendChild(r);
      }
      const copy = el('button', 'copy');
      copy.type = 'button';
      copy.setAttribute('aria-label', 'Copiar respuesta');
      copy.append(icon('i-copy'), el('span', null, 'Copiar'));
      copy.addEventListener('click', async () => {
        await copyText(m.text);
        copy.replaceChildren(icon('i-check'), el('span', null, 'Copiado'));
        setTimeout(() => copy.replaceChildren(icon('i-copy'), el('span', null, 'Copiar')), 1600);
      });
      actions.appendChild(copy);
      b.appendChild(actions);
    }
    return b;
  }

  function scrollToEnd() { els.messages.scrollTop = els.messages.scrollHeight; }

  function renderMessages() {
    els.messages.replaceChildren();
    const msgs = state.chat.messages || [];
    if (msgs.length === 0) {
      els.messages.appendChild(el('p', 'empty', 'Pregunta lo que quieras sobre «' + state.chat.name + '». Las respuestas indican la página de donde sale cada dato.'));
    }
    for (const m of msgs) els.messages.appendChild(buildMessage(m));
    scrollToEnd();
  }

  function appendMessage(m) {
    const empty = els.messages.querySelector('.empty');
    if (empty) empty.remove();
    const node = buildMessage(m);
    els.messages.appendChild(node);
    scrollToEnd();
    return node;
  }

  function showTyping() {
    const b = el('div', 'msg msg-bot');
    b.setAttribute('aria-label', 'Escribiendo respuesta');
    const dots = el('div', 'typing');
    dots.append(el('span'), el('span'), el('span'));
    b.appendChild(dots);
    els.messages.appendChild(b);
    scrollToEnd();
    return b;
  }

  function autosize() {
    els.question.style.height = 'auto';
    els.question.style.height = Math.min(els.question.scrollHeight, 140) + 'px';
  }
  function updateSend() { els.send.disabled = state.busy || els.question.value.trim() === ''; }

  async function send() {
    const q = els.question.value.trim();
    if (!q || state.busy || !state.chat) return;
    els.question.value = '';
    autosize();
    state.busy = true;
    updateSend();

    const userMsg = { role: 'user', text: q, pages: [] };
    state.chat.messages.push(userMsg);
    appendMessage(userMsg);
    const typing = showTyping();

    try {
      const r = await api.ask(state.chat.id, q);
      typing.remove();
      const botMsg = { role: 'assistant', text: r.answer, pages: r.pages || [] };
      state.chat.messages.push(botMsg);
      appendMessage(botMsg);
      if (botMsg.pages.length) goto(botMsg.pages[0]); // abre la primera página citada
    } catch (e) {
      typing.remove();
      appendMessage({ role: 'assistant', error: true, text: 'No pude responder: ' + (e.message || 'error desconocido') + '. Intenta de nuevo.', pages: [] });
    } finally {
      state.busy = false;
      updateSend();
      els.question.focus();
    }
  }

  els.send.addEventListener('click', send);
  els.question.addEventListener('input', () => { autosize(); updateSend(); });
  els.question.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
  });

  /* ---------------------------------------------------------------- */
  /* Eventos globales y arranque                                      */
  /* ---------------------------------------------------------------- */
  els.toggle.addEventListener('click', () => setSidebar(!isSidebarOpen(), true));
  els.scrim.addEventListener('click', () => setSidebar(false, true));
  els.newChat.addEventListener('click', () => { setSidebar(false); showHome(); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isSidebarOpen() && !els.confirm.open) setSidebar(false, true);
  });

  (async function init() {
    await refreshList();
    showHome();
  })();
})();
