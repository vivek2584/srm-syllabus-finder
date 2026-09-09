import pathlib

html = r"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>SRM Syllabus Finder</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
    <script>
      if (window.pdfjsLib) {
        pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
      }
    </script>
    <style>
      *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
      :root{
        --bg:#fafafa;--surface:#fff;--text:#1a1a1a;--text-secondary:#6b7280;
        --border:#e5e7eb;--primary:#111827;--primary-hover:#374151;
        --user-bg:#111827;--user-fg:#fff;--bot-bg:#f3f4f6;--bot-fg:#1a1a1a;
        --accent:#3b82f6;--error-bg:#fef2f2;--error-border:#ef4444;
        --font:"Inter",system-ui,-apple-system,sans-serif
      }
      @media(prefers-color-scheme:dark){:root{
        --bg:#0a0a0a;--surface:#111;--text:#e5e5e5;--text-secondary:#9ca3af;
        --border:#1f1f1f;--primary:#e5e5e5;--primary-hover:#d4d4d4;
        --user-bg:#e5e5e5;--user-fg:#0a0a0a;--bot-bg:#1a1a1a;--bot-fg:#e5e5e5;
        --accent:#60a5fa;--error-bg:#1c0a0a;--error-border:#dc2626
      }}
      body{font-family:var(--font);background:var(--bg);color:var(--text);height:100dvh;display:flex;flex-direction:column;overflow:hidden;-webkit-font-smoothing:antialiased}
      header{padding:16px 24px;border-bottom:1px solid var(--border);background:var(--surface);flex-shrink:0;display:flex;align-items:center;justify-content:space-between}
      header h1{font-size:.95rem;font-weight:600;letter-spacing:-.01em}
      header .meta{font-size:.75rem;color:var(--text-secondary)}
      #chat{flex:1;overflow-y:auto;padding:24px 16px;display:flex;flex-direction:column;gap:16px}
      #chat::-webkit-scrollbar{width:0}
      .msg{display:flex;max-width:100%;animation:fadeUp .15s ease-out}
      @keyframes fadeUp{from{opacity:0;transform:translateY(4px)}to{opacity:1}}
      .msg.user{justify-content:flex-end}
      .bubble{padding:10px 16px;border-radius:18px;max-width:min(680px,85%);line-height:1.6;font-size:.9rem;word-break:break-word}
      .msg.user .bubble{background:var(--user-bg);color:var(--user-fg);border-bottom-right-radius:4px}
      .msg.bot .bubble{background:var(--bot-bg);color:var(--bot-fg);border-bottom-left-radius:4px}
      .msg.bot.pdf-msg .bubble{max-width:min(900px,98%);padding:0;background:transparent}
      .pdf-preview-card{background:var(--surface);border:1px solid var(--border);border-radius:16px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.06);width:100%}
      .pdf-preview-header{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid var(--border);background:var(--bot-bg);gap:12px;flex-wrap:wrap}
      .pdf-preview-header-left{display:flex;align-items:center;gap:10px;min-width:0;flex:1}
      .pdf-course-badge{display:inline-flex;align-items:center;gap:5px;background:var(--accent);color:#fff;font-size:.75rem;font-weight:600;padding:3px 9px;border-radius:6px;letter-spacing:.03em;flex-shrink:0}
      .pdf-course-name{font-size:.85rem;font-weight:500;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .pdf-preview-actions{display:flex;gap:8px;flex-shrink:0;align-items:center}
      .pdf-action-btn{display:inline-flex;align-items:center;gap:5px;padding:5px 12px;border-radius:8px;font-size:.78rem;font-weight:500;font-family:var(--font);cursor:pointer;text-decoration:none;transition:all .15s;border:1px solid var(--border);background:transparent;color:var(--text-secondary)}
      .pdf-action-btn:hover{background:var(--bg);color:var(--text)}
      .pdf-action-btn svg{width:13px;height:13px;flex-shrink:0}
      .pdf-viewer-wrap{position:relative;width:100%;height:640px;background:#525659;transition:height .25s ease;overflow:hidden}
      .pdf-viewer-wrap.markdown-mode{height:auto;background:var(--surface)}
      .pdf-viewer-wrap iframe{width:100%;height:100%;border:none;display:block}
      .pdf-canvas-container{width:100%;height:100%;overflow-y:auto;overflow-x:hidden;display:flex;flex-direction:column;align-items:center;gap:12px;padding:16px 8px;background:#525659;-webkit-overflow-scrolling:touch}
      .pdf-canvas-container canvas{box-shadow:0 4px 14px rgba(0,0,0,.35);border-radius:4px;max-width:100%;height:auto!important;background:#fff}
      .pdf-loader{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;background:#525659;color:#d4d4d4;font-size:.82rem;pointer-events:none;transition:opacity .3s;z-index:2}
      .pdf-loader.hidden{opacity:0;display:none!important}
      .pdf-spinner{width:28px;height:28px;border:3px solid rgba(255,255,255,.15);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}
      @keyframes spin{to{transform:rotate(360deg)}}
      .pdf-error-state{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;height:260px;color:var(--text-secondary);font-size:.84rem;padding:24px;text-align:center;background:var(--bot-bg)}
      .pdf-error-state svg{width:32px;height:32px;opacity:.4}
      .pdf-markdown-body{padding:20px 24px;max-height:640px;overflow-y:auto}
      .pdf-markdown-notice{display:flex;align-items:center;gap:8px;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid var(--border);font-size:.75rem;color:var(--text-secondary)}
      .pdf-footer{padding:10px 14px 12px;border-top:1px solid var(--border);background:var(--bot-bg);font-size:.75rem;color:var(--text-secondary)}
      /* Markdown styles inside bubbles and PDF card */
      .content h2{font-size:1rem;font-weight:600;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid var(--border)}
      .content h3{font-size:.85rem;font-weight:600;color:var(--accent);margin:12px 0 4px;text-transform:uppercase;letter-spacing:.04em}
      .content p{margin:4px 0}
      .content ul,.content ol{padding-left:18px;margin:4px 0}
      .content li{margin:2px 0;font-size:.88rem}
      .content strong{font-weight:600}
      .content code{background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:1px 5px;font-size:.82em;font-family:monospace}
      .error-bubble{background:var(--error-bg)!important;border-left:2px solid var(--error-border)}
      #inputbar{padding:12px 16px 16px;background:var(--surface);border-top:1px solid var(--border);flex-shrink:0}
      #inputwrap{display:flex;gap:8px;position:relative;max-width:720px;margin:0 auto}
      #q{flex:1;padding:10px 16px;border:1px solid var(--border);border-radius:12px;font-size:.9rem;font-family:var(--font);outline:none;background:var(--bg);color:var(--text);transition:border-color .15s}
      #q::placeholder{color:var(--text-secondary)}
      #q:focus{border-color:var(--accent)}
      #sendbtn{padding:10px 18px;background:var(--primary);color:var(--bg);border:none;border-radius:12px;font-size:.85rem;font-weight:500;font-family:var(--font);cursor:pointer;transition:background .15s;flex-shrink:0}
      #sendbtn:hover{background:var(--primary-hover)}
      #sendbtn:disabled{opacity:.4;cursor:default}
      #suggestions{position:absolute;bottom:calc(100% + 4px);left:0;right:80px;background:var(--surface);border:1px solid var(--border);border-radius:10px;box-shadow:0 4px 20px rgba(0,0,0,.08);max-height:200px;overflow-y:auto;z-index:100;display:none}
      .sug-item{padding:8px 14px;cursor:pointer;display:flex;gap:10px;align-items:baseline;font-size:.85rem;transition:background .1s}
      .sug-item:first-child{border-radius:10px 10px 0 0}
      .sug-item:last-child{border-radius:0 0 10px 10px}
      .sug-item:hover,.sug-item.active{background:var(--bot-bg)}
      .sug-code{font-weight:600;font-family:monospace;font-size:.8rem;color:var(--accent);flex-shrink:0}
      .sug-name{color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .dot-flashing{display:inline-flex;gap:4px;padding:4px 0}
      .dot-flashing span{width:6px;height:6px;border-radius:50%;background:var(--text-secondary);animation:blink 1.4s infinite both}
      .dot-flashing span:nth-child(2){animation-delay:.2s}
      .dot-flashing span:nth-child(3){animation-delay:.4s}
      @keyframes blink{0%,80%,100%{opacity:.2}40%{opacity:1}}
      .welcome{display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;gap:8px;color:var(--text-secondary);text-align:center;padding:40px 20px}
      .welcome h2{font-size:1.1rem;font-weight:600;color:var(--text)}
      .welcome p{font-size:.85rem;max-width:360px;line-height:1.5}
      @media(max-width:480px){
        header{padding:12px 16px}
        #chat{padding:16px 10px}
        .bubble{max-width:92%;padding:8px 12px}
        .pdf-viewer-wrap{height:55dvh;min-height:320px}
        .pdf-viewer-wrap.markdown-mode{height:auto}
        .pdf-markdown-body{max-height:420px}
      }
      .segmented-control{display:flex;background:var(--bg);padding:4px;border-radius:8px;border:1px solid var(--border)}
      .segmented-control input[type=radio]{display:none}
      .segmented-control label{padding:4px 12px;font-size:.8rem;font-weight:500;cursor:pointer;color:var(--text-secondary);transition:all .2s ease;border-radius:6px}
      .segmented-control input[type=radio]:checked+label{color:#fff;background:var(--accent);box-shadow:0 1px 3px rgba(0,0,0,.1)}
      @media(prefers-color-scheme:dark){.segmented-control input[type=radio]:checked+label{color:#000}}

      /* ── Full-screen modal overlay ── */
      #pdf-modal{display:none;position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.7);backdrop-filter:blur(4px);animation:fadeIn .18s ease}
      #pdf-modal.open{display:flex;flex-direction:column}
      @keyframes fadeIn{from{opacity:0}to{opacity:1}}
      #pdf-modal-inner{display:flex;flex-direction:column;width:min(1200px,98vw);max-height:96dvh;margin:auto;background:var(--surface);border-radius:16px;overflow:hidden;box-shadow:0 24px 80px rgba(0,0,0,.4);animation:slideUp .2s ease}
      @keyframes slideUp{from{transform:translateY(20px);opacity:0}to{transform:translateY(0);opacity:1}}
      #pdf-modal-header{display:flex;align-items:center;justify-content:space-between;padding:14px 20px;border-bottom:1px solid var(--border);background:var(--bot-bg);gap:12px;flex-shrink:0}
      #pdf-modal-title{display:flex;align-items:center;gap:10px;min-width:0;flex:1;font-size:.9rem;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      #pdf-modal-close{width:32px;height:32px;border-radius:50%;border:none;background:var(--border);color:var(--text);cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:1.1rem;transition:background .15s}
      #pdf-modal-close:hover{background:var(--accent);color:#fff}
      #pdf-modal-body{flex:1;overflow:hidden;display:flex;flex-direction:column;min-height:0}
      #pdf-modal-body iframe{width:100%;height:100%;border:none;flex:1}
      #pdf-modal-body .pdf-markdown-body{flex:1;overflow-y:auto;max-height:none}
    </style>
  </head>
  <body>
    <header>
      <h1>SRM Syllabus Finder</h1>
      <div style="display:flex;gap:12px;align-items:center">
        <div class="segmented-control">
          <input type="radio" name="reg" id="reg-2021" value="2021" checked onchange="changeRegulation()">
          <label for="reg-2021">2021</label>
          <input type="radio" name="reg" id="reg-2026" value="2026" onchange="changeRegulation()">
          <label for="reg-2026">2026</label>
        </div>
        <span class="meta" id="stats-badge"></span>
      </div>
    </header>
    <div id="chat"></div>
    <div id="inputbar">
      <div id="inputwrap">
        <div id="suggestions"></div>
        <input id="q" type="text" placeholder="Ask about any course or topic..." autocomplete="off" spellcheck="false"/>
        <button id="sendbtn" onclick="handleSend()">Send</button>
      </div>
    </div>

    <!-- Full-screen modal for expanded view -->
    <div id="pdf-modal" onclick="closePdfModal(event)">
      <div id="pdf-modal-inner">
        <div id="pdf-modal-header">
          <div id="pdf-modal-title"></div>
          <button id="pdf-modal-close" onclick="closePdfModal()" aria-label="Close">&times;</button>
        </div>
        <div id="pdf-modal-body"></div>
      </div>
    </div>

    <script>
      marked.setOptions({breaks:true,gfm:true});
      const chat = document.getElementById('chat');
      const input = document.getElementById('q');
      const sendBtn = document.getElementById('sendbtn');
      const sugBox = document.getElementById('suggestions');
      let sugIndex = -1, sugItems = [], sugTimer = null;
      let lastQueryContext = 'Syllabus';
      let currentRegulation = '2021';
      let mid = 0;

      const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent) || ('ontouchstart' in window && navigator.maxTouchPoints > 1);

      window.addEventListener('DOMContentLoaded', () => { resetChat(); input.focus(); });

      function resetChat() {
        chat.innerHTML =
          '<div class="welcome">' +
          '<h2>Ask anything about your syllabus</h2>' +
          '<p>Search by course code, ask about prerequisites, compare courses, or explore topics.</p>' +
          '<div style="margin-top:20px;padding:10px 16px;background:var(--bot-bg);border-radius:12px;border:1px solid var(--border);font-size:.85rem;color:var(--text-secondary);display:inline-flex;align-items:center;gap:8px">' +
          '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--accent)"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>' +
          '<span><strong>Tip:</strong> Switch between <strong style="color:var(--text)">2021</strong> and <strong style="color:var(--text)">2026</strong> syllabi using the toggle above.</span>' +
          '</div></div>';
        loadStats();
      }

      function changeRegulation() {
        currentRegulation = document.querySelector('input[name="reg"]:checked').value;
        resetChat();
      }

      async function loadStats() {
        try {
          const r = await fetch('/api/stats?regulation=' + currentRegulation);
          if (!r.ok) return;
          const d = await r.json();
          document.getElementById('stats-badge').textContent = d.total_courses + ' courses';
        } catch {}
      }

      function isDirectSearch(q) { return /^\s*(?:21|26)[A-Z]{2,5}\d{3,4}[A-Z]?\s*$/i.test(q); }
      function clearWelcome() { const w = chat.querySelector('.welcome'); if (w) w.remove(); }
      function scroll() { chat.scrollTop = chat.scrollHeight; }
      function esc(s) {
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
      }

      async function handleSend() { const q = input.value.trim(); if (!q) return; sendQuery(q); }

      async function sendQuery(q) {
        lastQueryContext = q;
        input.value = '';
        hideSuggestions();
        clearWelcome();
        appendUserMsg(q);
        sendBtn.disabled = true;
        const isSyllabus = isDirectSearch(q);

        const tid = appendTyping();
        try {
          const r = await fetch('/api/search?q=' + encodeURIComponent(q) + '&regulation=' + currentRegulation);
          const data = r.ok ? await r.json() : null;
          if (data && data.type === 'course') {
            removeEl(tid);
            appendCoursePdfPreview(data.course, data.response || '');
            sendBtn.disabled = false; input.focus(); return;
          }
          if (data && data.type === 'list') {
            removeEl(tid);
            appendBotMsg(data.response, false, true);
            sendBtn.disabled = false; input.focus(); return;
          }
          removeEl(tid);
          if (isSyllabus) {
            appendBotMsg(data ? data.response || '_No results._' : '**Error:** Unknown', !r.ok, true);
            sendBtn.disabled = false; input.focus(); return;
          }
        } catch {
          removeEl(tid);
          if (isSyllabus) {
            appendBotMsg('**Cannot reach server.**', true);
            sendBtn.disabled = false; input.focus(); return;
          }
        }

        const botId = appendBotMsgEmpty();
        let full = '';
        try {
          const res = await fetch('/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({question: q, regulation: currentRegulation})
          });
          if (!res.ok) {
            const err = await res.json();
            updateBotMsg(botId, '**Error:** ' + (err.detail || 'Unknown'), true);
            sendBtn.disabled = false; input.focus(); return;
          }
          const reader = res.body.getReader();
          const dec = new TextDecoder();
          let buf = '';
          while (true) {
            const {done, value} = await reader.read();
            if (done) { updateBotMsg(botId, full, false, true); break; }
            buf += dec.decode(value, {stream: true});
            const lines = buf.split('\n'); buf = lines.pop();
            for (const line of lines) {
              if (!line.startsWith('data: ')) continue;
              const payload = line.slice(6).trim();
              if (payload === '[DONE]') continue;
              try {
                const d = JSON.parse(payload);
                if (d.error) { updateBotMsg(botId, '**Error:** ' + d.error, true); sendBtn.disabled = false; input.focus(); return; }
                if (d.text) { full += d.text; updateBotMsg(botId, full); }
              } catch {}
            }
          }
          if (!full) updateBotMsg(botId, 'No response generated. Try rephrasing.', true);
        } catch {
          updateBotMsg(botId, '**Cannot reach server.**', true);
        } finally {
          sendBtn.disabled = false; input.focus();
        }
      }

      /* ── PDF.js HTML5 Canvas Renderer ────────────────────────── */
      async function renderPdfWithPdfJs(pdfUrl, wrapEl, loaderEl) {
        try {
          if (!window.pdfjsLib) return false;
          const loadingTask = pdfjsLib.getDocument(pdfUrl);
          const pdfDoc = await loadingTask.promise;

          const container = document.createElement('div');
          container.className = 'pdf-canvas-container';

          const wrapWidth = wrapEl.clientWidth || (window.innerWidth < 480 ? window.innerWidth - 32 : 680);
          const targetWidth = Math.max(280, wrapWidth - 24);
          const dpr = window.devicePixelRatio || 1;

          for (let pageNum = 1; pageNum <= pdfDoc.numPages; pageNum++) {
            const page = await pdfDoc.getPage(pageNum);
            const unscaledViewport = page.getViewport({ scale: 1.0 });
            const scale = targetWidth / unscaledViewport.width;
            const viewport = page.getViewport({ scale: scale });

            const canvas = document.createElement('canvas');
            const context = canvas.getContext('2d');

            canvas.width = Math.floor(viewport.width * dpr);
            canvas.height = Math.floor(viewport.height * dpr);
            canvas.style.width = Math.floor(viewport.width) + 'px';
            canvas.style.height = Math.floor(viewport.height) + 'px';

            const renderContext = {
              canvasContext: context,
              viewport: viewport,
              transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null
            };

            await page.render(renderContext).promise;
            container.appendChild(canvas);

            if (pageNum === 1 && loaderEl) {
              loaderEl.classList.add('hidden');
            }
          }

          wrapEl.appendChild(container);
          if (loaderEl) loaderEl.classList.add('hidden');
          return true;
        } catch (err) {
          console.error('PDF.js render error:', err);
          if (loaderEl) loaderEl.classList.add('hidden');
          return false;
        }
      }

      /* ── PDF Preview Card ─────────────────────────────────────── */

      // Store per-card data for the modal
      const _cardData = {};

      async function appendCoursePdfPreview(course, markdownFallback) {
        const id = ++mid;
        const code = course.code || '';
        const name = course.name || '';
        const pdfUrl = '/api/pdf/' + encodeURIComponent(code) + '?regulation=' + currentRegulation;
        const ltpc = (course.l||0) + '-' + (course.t||0) + '-' + (course.p||0) + '-' + (course.c||0);
        const cat = course.category || '';
        const credits = course.c != null ? (course.c + ' credits') : '';
        const subtitle = [cat, credits, 'L-T-P-C: ' + ltpc].filter(Boolean).join('  \u00b7  ');

        // Store for modal use
        _cardData[id] = { code, name, pdfUrl, markdownFallback: markdownFallback || '', hasPdf: false };

        const card = document.createElement('div');
        card.className = 'msg bot pdf-msg';
        card.id = 'm' + id;
        card.setAttribute('data-query', lastQueryContext);

        const header = document.createElement('div');
        header.className = 'pdf-preview-header';
        header.innerHTML =
          '<div class="pdf-preview-header-left">' +
            '<span class="pdf-course-badge">' +
              '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">' +
                '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' +
                '<polyline points="14 2 14 8 20 8"/>' +
              '</svg>' +
              esc(code) +
            '</span>' +
            '<span class="pdf-course-name" title="' + esc(name) + '">' + esc(name) + '</span>' +
          '</div>' +
          '<div class="pdf-preview-actions">' +
            '<a id="dl-btn-' + id + '" class="pdf-action-btn" href="' + pdfUrl + '" download="' + esc(code) + '_Syllabus.pdf">' +
              '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
                '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>' +
                '<polyline points="7 10 12 15 17 10"/>' +
                '<line x1="12" y1="15" x2="12" y2="3"/>' +
              '</svg>' +
              'Download' +
            '</a>' +
            '<button id="expand-btn-' + id + '" class="pdf-action-btn" onclick="openPdfModal(' + id + ')">' +
              '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
                '<polyline points="15 3 21 3 21 9"/>' +
                '<polyline points="9 21 3 21 3 15"/>' +
                '<line x1="21" y1="3" x2="14" y2="10"/>' +
                '<line x1="3" y1="21" x2="10" y2="14"/>' +
              '</svg>' +
              'Expand' +
            '</button>' +
          '</div>';

        const viewerWrap = document.createElement('div');
        viewerWrap.className = 'pdf-viewer-wrap';
        viewerWrap.id = 'pdf-wrap-' + id;

        const loader = document.createElement('div');
        loader.className = 'pdf-loader';
        loader.id = 'pdf-loader-' + id;
        loader.innerHTML = '<div class="pdf-spinner"></div><span>Loading syllabus\u2026</span>';
        viewerWrap.appendChild(loader);

        const footer = document.createElement('div');
        footer.className = 'pdf-footer';
        footer.textContent = subtitle;

        const pdfCard = document.createElement('div');
        pdfCard.className = 'pdf-preview-card';
        pdfCard.appendChild(header);
        pdfCard.appendChild(viewerWrap);
        pdfCard.appendChild(footer);

        const bubble = document.createElement('div');
        bubble.className = 'bubble';
        bubble.appendChild(pdfCard);
        card.appendChild(bubble);

        chat.appendChild(card);
        card.scrollIntoView({behavior: 'smooth', block: 'start'});

        // Probe PDF endpoint and render using PDF.js
        try {
          const probe = await fetch(pdfUrl);
          const ct = probe.headers.get('Content-Type') || '';
          if (!probe.ok || !ct.includes('pdf')) {
            let msg = 'PDF not available for this course yet.';
            try { const j = await probe.json(); if (j.detail) msg = j.detail; } catch {}
            _cardData[id].hasPdf = false;
            showPdfError(id, msg, markdownFallback);
          } else {
            _cardData[id].hasPdf = true;
            const wrap = document.getElementById('pdf-wrap-' + id);
            const lo = document.getElementById('pdf-loader-' + id);
            if (wrap) {
              const rendered = await renderPdfWithPdfJs(pdfUrl, wrap, lo);
              if (!rendered) {
                // Fallback to iframe if PDF.js failed
                const iframe = document.createElement('iframe');
                iframe.id = 'pdf-frame-' + id;
                iframe.title = 'Syllabus ' + code;
                iframe.onload = function() {
                  if (lo) lo.classList.add('hidden');
                };
                iframe.src = pdfUrl + '#toolbar=1&navpanes=0&scrollbar=1&view=FitH';
                wrap.appendChild(iframe);
              }
            }
          }
        } catch (err) {
          _cardData[id].hasPdf = false;
          showPdfError(id, 'Could not reach the server.', markdownFallback);
        }
      }

      function showMarkdownContent(id, md) {
        const wrap = document.getElementById('pdf-wrap-' + id);
        if (!wrap) return;
        wrap.classList.add('markdown-mode');
        wrap.innerHTML =
          '<div class="pdf-markdown-body">' +
            '<div class="pdf-markdown-notice">' +
              '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>' +
              'PDF not available \u2014 showing extracted syllabus data' +
            '</div>' +
            '<div class="content" style="font-size:.875rem">' + marked.parse(md || '') + '</div>' +
          '</div>';
      }

      function showPdfError(id, msg, markdownFallback) {
        if (markdownFallback) {
          showMarkdownContent(id, markdownFallback);
        } else {
          const wrap = document.getElementById('pdf-wrap-' + id);
          if (!wrap) return;
          wrap.innerHTML =
            '<div class="pdf-error-state">' +
              '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>' +
              '<span>' + esc(msg) + '</span>' +
            '</div>';
        }
        // Disable Download button
        const dlBtn = document.getElementById('dl-btn-' + id);
        if (dlBtn) {
          dlBtn.removeAttribute('href');
          dlBtn.removeAttribute('download');
          dlBtn.style.opacity = '0.38';
          dlBtn.style.cursor = 'not-allowed';
          dlBtn.title = 'PDF not available on server';
          dlBtn.onclick = e => e.preventDefault();
        }
      }

      /* ── Full-screen modal ─────────────────────────────────────── */
      function openPdfModal(id) {
        const data = _cardData[id];
        if (!data) return;

        const modal = document.getElementById('pdf-modal');
        const title = document.getElementById('pdf-modal-title');
        const body = document.getElementById('pdf-modal-body');

        title.innerHTML =
          '<span class="pdf-course-badge">' +
            '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">' +
              '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' +
              '<polyline points="14 2 14 8 20 8"/>' +
            '</svg>' +
            esc(data.code) +
          '</span>' +
          '<span style="overflow:hidden;text-overflow:ellipsis">' + esc(data.name) + '</span>';

        body.innerHTML = '';

        if (data.hasPdf) {
          const wrap = document.createElement('div');
          wrap.style.cssText = 'position:relative;width:100%;height:100%;flex:1;min-height:70dvh;background:#525659;overflow:hidden';
          const loader = document.createElement('div');
          loader.className = 'pdf-loader';
          loader.innerHTML = '<div class="pdf-spinner"></div><span>Loading syllabus\u2026</span>';
          wrap.appendChild(loader);
          body.appendChild(wrap);

          renderPdfWithPdfJs(data.pdfUrl, wrap, loader).then(rendered => {
            if (!rendered) {
              wrap.innerHTML = '';
              const iframe = document.createElement('iframe');
              iframe.style.cssText = 'width:100%;height:100%;border:none;flex:1;min-height:70dvh';
              iframe.title = 'Syllabus ' + data.code;
              iframe.src = data.pdfUrl;
              wrap.appendChild(iframe);
            }
          });
        } else {
          body.innerHTML =
            '<div class="pdf-markdown-body" style="flex:1;overflow-y:auto;max-height:calc(92dvh - 64px)">' +
              '<div class="content">' + marked.parse(data.markdownFallback || '') + '</div>' +
            '</div>';
        }

        modal.classList.add('open');
        document.body.style.overflow = 'hidden';
      }

      function closePdfModal(e) {
        // Close only if clicking backdrop or close button (not the inner card)
        if (e && e.target !== document.getElementById('pdf-modal') && !e.target.closest('#pdf-modal-close')) return;
        const modal = document.getElementById('pdf-modal');
        modal.classList.remove('open');
        document.getElementById('pdf-modal-body').innerHTML = '';
        document.body.style.overflow = '';
      }

      // Close modal on Escape key
      document.addEventListener('keydown', e => { if (e.key === 'Escape') closePdfModal({target: document.getElementById('pdf-modal')}); });

      /* ── Message helpers ───────────────────────────────────────── */
      function appendUserMsg(text) {
        const id = ++mid;
        const el = document.createElement('div');
        el.className = 'msg user'; el.id = 'm' + id;
        el.innerHTML = '<div class="bubble">' + esc(text) + '</div>';
        chat.appendChild(el); scroll(); return id;
      }

      function appendBotMsg(md, err, done) {
        const id = ++mid;
        const el = document.createElement('div');
        el.className = 'msg bot'; el.id = 'm' + id;
        el.setAttribute('data-query', lastQueryContext);
        el.innerHTML = '<div class="bubble' + (err ? ' error-bubble' : '') + '"><div class="content">' + marked.parse(md) + '</div></div>';
        chat.appendChild(el);
        if (done) el.scrollIntoView({behavior: 'smooth', block: 'start'}); else scroll();
        return id;
      }

      function appendBotMsgEmpty() {
        const id = ++mid;
        const el = document.createElement('div');
        el.className = 'msg bot'; el.id = 'm' + id;
        el.setAttribute('data-query', lastQueryContext);
        el.innerHTML = '<div class="bubble"><div class="dot-flashing"><span></span><span></span><span></span></div></div>';
        chat.appendChild(el); scroll(); return id;
      }

      function updateBotMsg(id, md, err, done) {
        const el = document.getElementById('m' + id); if (!el) return;
        const b = el.querySelector('.bubble');
        b.className = 'bubble' + (err ? ' error-bubble' : '');
        b.innerHTML = '<div class="content">' + marked.parse(md) + '</div>';
        if (done) el.scrollIntoView({behavior: 'smooth', block: 'start'}); else scroll();
      }

      function appendTyping() {
        const id = ++mid;
        const el = document.createElement('div');
        el.className = 'msg bot'; el.id = 'm' + id;
        el.innerHTML = '<div class="bubble"><div class="dot-flashing"><span></span><span></span><span></span></div></div>';
        chat.appendChild(el); scroll(); return id;
      }

      function removeEl(id) { document.getElementById('m' + id)?.remove(); }

      /* ── Keyboard & autocomplete ───────────────────────────────── */
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          sugIndex >= 0 && sugItems[sugIndex] ? selectSug(sugIndex) : handleSend();
          return;
        }
        if (e.key === 'ArrowDown') { e.preventDefault(); moveSug(1); }
        if (e.key === 'ArrowUp') { e.preventDefault(); moveSug(-1); }
        if (e.key === 'Escape') hideSuggestions();
      });

      input.addEventListener('input', () => { clearTimeout(sugTimer); sugTimer = setTimeout(fetchSuggestions, 200); });

      async function fetchSuggestions() {
        const q = input.value.trim();
        if (q.length < 2) { hideSuggestions(); return; }
        try {
          const r = await fetch('/api/suggest?q=' + encodeURIComponent(q) + '&regulation=' + currentRegulation);
          const d = await r.json();
          sugItems = d.suggestions || [];
          renderSuggestions();
        } catch {}
      }

      function renderSuggestions() {
        if (!sugItems.length) { hideSuggestions(); return; }
        sugIndex = -1;
        sugBox.innerHTML = sugItems.map((s, i) =>
          '<div class="sug-item" onclick="selectSug(' + i + ')">' +
            '<span class="sug-code">' + esc(s.code) + '</span>' +
            '<span class="sug-name">' + esc(s.name) + '</span>' +
          '</div>'
        ).join('');
        sugBox.style.display = 'block';
      }

      function hideSuggestions() { sugBox.style.display = 'none'; sugIndex = -1; }

      function moveSug(dir) {
        const items = sugBox.querySelectorAll('.sug-item'); if (!items.length) return;
        items[sugIndex]?.classList.remove('active');
        sugIndex = Math.max(-1, Math.min(items.length - 1, sugIndex + dir));
        if (sugIndex >= 0) {
          items[sugIndex].classList.add('active');
          items[sugIndex].scrollIntoView({block: 'nearest'});
          input.value = sugItems[sugIndex].code;
        }
      }

      function selectSug(i) { if (!sugItems[i]) return; hideSuggestions(); sendQuery(sugItems[i].code); }

      document.addEventListener('click', (e) => { if (!e.target.closest('#inputwrap')) hideSuggestions(); });
    </script>
  </body>
</html>"""

p = pathlib.Path('frontend/index.html')
p.write_text(html, encoding='utf-8')
lines = html.count('\n')
print(f'OK: wrote {len(html)} bytes, {lines} lines to {p}')
