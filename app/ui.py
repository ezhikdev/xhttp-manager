LOGIN = r'''<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Вход — XHTTP Manager</title>
  <style>
    *,*::before,*::after{box-sizing:border-box}*{margin:0}html{font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;color-scheme:dark}
    :root{--bg:#0a0a0a;--card:#111;--card-2:#161616;--text:#f0ede8;--muted:#8b8781;--faint:#55514c;--accent:#e7e3dc;--accent-dim:rgba(231,227,220,.1);--accent-border:rgba(231,227,220,.2);--border:rgba(255,255,255,.075);--danger:#ff7a7a}
    body{min-height:100vh;display:grid;place-items:center;padding:24px;background:var(--bg);color:var(--text);line-height:1.5}
    body::before{content:"";position:fixed;inset:0;pointer-events:none;background:radial-gradient(ellipse 600px 360px at 50% -120px,rgba(231,227,220,.07),transparent 70%),url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='4'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.03'/%3E%3C/svg%3E")}
    .shell{position:relative;width:min(100%,400px)}.brand{display:flex;align-items:center;gap:10px;margin:0 0 24px;font:700 14px "JetBrains Mono",ui-monospace,monospace;letter-spacing:.04em;color:var(--accent)}
    .mark{display:grid;place-items:center;width:32px;height:32px;border:1px solid var(--accent-border);border-radius:9px;background:var(--accent-dim)}.mark svg{width:16px}
    .card{padding:30px;background:var(--card);border:1px solid var(--border);border-radius:16px;box-shadow:0 24px 80px rgba(0,0,0,.35)}
    .eyebrow{font:500 11px "JetBrains Mono",ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:10px}h1{font-size:28px;letter-spacing:-.035em;line-height:1.15;margin-bottom:8px}.lead{font-size:14px;color:var(--muted);margin-bottom:24px}
    label{display:block;font-size:13px;font-weight:600;margin:16px 0 7px}input{width:100%;height:46px;border:1px solid var(--border);border-radius:9px;background:#0d0d0d;color:var(--text);font:14px "JetBrains Mono",ui-monospace,monospace;padding:0 13px;outline:none;transition:border-color .2s,box-shadow .2s}input::placeholder{color:var(--faint)}input:focus{border-color:var(--accent-border);box-shadow:0 0 0 3px var(--accent-dim)}
    button{width:100%;min-height:46px;margin-top:22px;border:0;border-radius:9px;background:var(--accent);color:#0a0a0a;font:600 14px Inter,ui-sans-serif,system-ui;cursor:pointer;transition:background .2s,transform .2s}button:hover{background:#fff}button:active{transform:scale(.985)}button:focus-visible{outline:3px solid rgba(231,227,220,.3);outline-offset:2px}
    .error{padding:11px 13px;margin:0 0 16px;border:1px solid rgba(255,122,122,.25);border-radius:9px;background:rgba(255,122,122,.08);color:#ffb0b0;font-size:13px}
    .foot{margin-top:18px;text-align:center;color:var(--faint);font:11px "JetBrains Mono",ui-monospace,monospace}
    @media(max-width:480px){body{padding:16px}.card{padding:24px 20px}}
  </style>
</head>
<body>
  <main class="shell">
    <div class="brand"><span class="mark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg></span>xhttp.manager</div>
    <section class="card" aria-labelledby="login-title">
      <div class="eyebrow">Панель управления</div>
      <h1 id="login-title">Вход в систему</h1>
      <p class="lead">Введите данные, созданные во время установки.</p>
      <!--ERROR-->
      <form method="post" action="__PATH__/login">
        <label for="username">Логин</label>
        <input id="username" name="username" autocomplete="username" required autofocus>
        <label for="password">Пароль</label>
        <input id="password" name="password" type="password" autocomplete="current-password" required>
        <button type="submit">Войти в панель</button>
      </form>
    </section>
    <p class="foot">XHTTP Manager · nginx control plane</p>
  </main>
</body>
</html>'''


HTML = r'''<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>XHTTP Manager</title>
  <style>
    *,*::before,*::after{box-sizing:border-box}*{margin:0}html{font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;color-scheme:dark;scroll-behavior:smooth}
    :root{--bg:#0a0a0a;--card:#111;--card-hover:#161616;--input:#0d0d0d;--text:#f0ede8;--muted:#8b8781;--faint:#55514c;--accent:#e7e3dc;--accent-dim:rgba(231,227,220,.1);--accent-border:rgba(231,227,220,.2);--border:rgba(255,255,255,.075);--success:#73d89b;--danger:#ff7a7a;--danger-dim:rgba(255,122,122,.09);--mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Consolas,monospace}
    body{min-height:100vh;background:var(--bg);color:var(--text);font-size:15px;line-height:1.55;overflow-x:hidden}
    body::before{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;opacity:.55;background:radial-gradient(ellipse 760px 430px at 50% -180px,rgba(231,227,220,.065),transparent 72%),url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='4'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.025'/%3E%3C/svg%3E")}
    button,input{font:inherit}button{touch-action:manipulation}.topbar{position:sticky;top:0;z-index:20;height:58px;border-bottom:1px solid var(--border);background:rgba(10,10,10,.78);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}
    .topbar-inner{width:min(1180px,calc(100% - 40px));height:100%;margin:auto;display:flex;align-items:center;justify-content:space-between;gap:16px}.brand{display:flex;align-items:center;gap:10px;font:700 13px var(--mono);letter-spacing:.04em;color:var(--accent)}.mark{display:grid;place-items:center;width:30px;height:30px;border:1px solid var(--accent-border);border-radius:8px;background:var(--accent-dim)}.mark svg{width:15px}.brand span:last-child{color:var(--muted);font-weight:400}
    .top-actions{display:flex;align-items:center;gap:10px}.guard{display:flex;align-items:center;gap:7px;color:var(--muted);font:11px var(--mono)}.guard-dot{width:6px;height:6px;border-radius:50%;background:var(--success);box-shadow:0 0 0 4px rgba(115,216,155,.08)}
    .page{position:relative;z-index:1;width:min(1180px,calc(100% - 40px));margin:0 auto;padding:54px 0 72px}.hero{margin-bottom:30px}.eyebrow{display:flex;align-items:center;gap:9px;margin-bottom:12px;color:var(--muted);font:500 11px var(--mono);letter-spacing:.1em;text-transform:uppercase}.eyebrow::before{content:"";width:20px;height:1px;background:var(--accent);opacity:.45}h1{font-size:clamp(34px,5vw,54px);line-height:1.05;letter-spacing:-.045em;margin-bottom:12px}h1 em{color:var(--accent);font-style:italic}.hero p{max-width:640px;color:var(--muted);font-size:15px}
    .layout{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(280px,.7fr);gap:16px;align-items:start}.card{background:var(--card);border:1px solid var(--border);border-radius:15px;overflow:hidden}.card-head{padding:20px 22px;border-bottom:1px solid var(--border);display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.card-title{font-size:16px;font-weight:650;letter-spacing:-.015em}.card-desc{margin-top:3px;color:var(--muted);font-size:13px}.card-body{padding:22px}
    .form-grid{display:grid;grid-template-columns:1.35fr 1fr .65fr;gap:14px}.field{min-width:0}.field-wide{grid-column:1/-1}label,.field-label{display:block;margin-bottom:7px;color:var(--text);font-size:12px;font-weight:600}.hint{display:block;margin-top:6px;color:var(--faint);font-size:11px;line-height:1.45}.mono{font-family:var(--mono)}
    input[type=text],input[type=number]{width:100%;height:44px;padding:0 12px;border:1px solid var(--border);border-radius:9px;background:var(--input);color:var(--text);font:13px var(--mono);outline:none;transition:border-color .2s,box-shadow .2s,opacity .2s}input::placeholder{color:var(--faint)}input:focus{border-color:var(--accent-border);box-shadow:0 0 0 3px var(--accent-dim)}input:disabled{opacity:.42;cursor:not-allowed}
    .stub-control{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding:15px;border:1px solid var(--border);border-radius:11px;background:rgba(255,255,255,.018)}.stub-copy{min-width:0}.stub-copy strong{display:block;font-size:13px;margin-bottom:3px}.stub-copy span{display:block;color:var(--muted);font-size:12px;line-height:1.45}.switch{position:relative;display:inline-flex;flex:0 0 auto;width:44px;height:26px;margin:1px 0 0;cursor:pointer}.switch input{position:absolute;opacity:0;width:1px;height:1px}.track{position:absolute;inset:0;border:1px solid var(--accent-border);border-radius:99px;background:#242321;transition:background .2s,border-color .2s}.track::after{content:"";position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;background:var(--muted);transition:transform .2s,background .2s}.switch input:checked+.track{background:var(--accent);border-color:var(--accent)}.switch input:checked+.track::after{transform:translateX(18px);background:#111}.switch input:focus-visible+.track{outline:3px solid rgba(231,227,220,.28);outline-offset:2px}
    .stub-path{margin-top:12px;transition:opacity .2s}.stub-path.is-disabled{opacity:.55}.actions{display:flex;align-items:center;gap:9px;margin-top:20px;flex-wrap:wrap}.btn{min-height:42px;padding:0 15px;border:1px solid transparent;border-radius:9px;display:inline-flex;align-items:center;justify-content:center;gap:8px;cursor:pointer;font-size:13px;font-weight:600;transition:background .2s,border-color .2s,color .2s,transform .2s,opacity .2s}.btn:hover{transform:translateY(-1px)}.btn:active{transform:scale(.98)}.btn:focus-visible{outline:3px solid rgba(231,227,220,.25);outline-offset:2px}.btn:disabled{opacity:.5;cursor:wait;transform:none}.btn svg{width:15px;height:15px}.primary{background:var(--accent);color:#0a0a0a}.primary:hover{background:#fff}.ghost{background:transparent;border-color:var(--border);color:var(--muted)}.ghost:hover{background:var(--accent-dim);border-color:var(--accent-border);color:var(--accent)}.danger{background:transparent;border-color:rgba(255,122,122,.2);color:#ffaaaa}.danger:hover{background:var(--danger-dim);border-color:rgba(255,122,122,.35)}.small{min-height:36px;padding:0 11px;font-size:12px}.icon-btn{width:38px;padding:0}
    .flow{padding:22px}.flow-title{font:500 11px var(--mono);letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin-bottom:18px}.flow-step{position:relative;padding:0 0 19px 30px;color:var(--muted);font-size:12px}.flow-step:last-child{padding-bottom:0}.flow-step::before{content:"";position:absolute;left:5px;top:8px;bottom:-3px;width:1px;background:var(--border)}.flow-step:last-child::before{display:none}.flow-dot{position:absolute;left:0;top:3px;width:11px;height:11px;border-radius:50%;border:2px solid var(--card);background:var(--faint);box-shadow:0 0 0 1px var(--border)}.flow-step.current .flow-dot{background:var(--success)}.flow-step strong{display:block;margin-bottom:2px;color:var(--text);font-size:13px}.flow code{font:11px var(--mono);color:var(--accent);overflow-wrap:anywhere}
    .notice{margin-top:16px;padding:13px 14px;border:1px solid var(--accent-border);border-radius:10px;background:var(--accent-dim);color:var(--muted);font-size:12px}.notice strong{color:var(--accent)}
    .list-card{margin-top:16px}.list-head-actions{display:flex;align-items:center;gap:9px}.count{padding:3px 8px;border:1px solid var(--border);border-radius:6px;color:var(--muted);font:11px var(--mono)}.origin-list{padding:8px}.origin-item{display:grid;grid-template-columns:minmax(220px,1.25fr) minmax(260px,1fr) auto;gap:18px;align-items:center;padding:15px 14px;border-radius:10px;transition:background .2s}.origin-item+.origin-item{border-top:1px solid var(--border);border-radius:0}.origin-item:hover{background:var(--card-hover)}.origin-domain{min-width:0}.domain-line{display:flex;align-items:center;gap:9px;font-weight:600;overflow-wrap:anywhere}.live-dot{width:6px;height:6px;border-radius:50%;background:var(--success);flex:0 0 auto}.route-meta{margin:4px 0 0 15px;color:var(--faint);font:11px var(--mono)}.route{display:flex;align-items:center;gap:8px;min-width:0;color:var(--muted);font:12px var(--mono)}.route code{color:var(--accent);overflow-wrap:anywhere}.arrow{color:var(--faint)}.tag{display:inline-flex;align-items:center;margin-top:7px;padding:3px 7px;border:1px solid var(--border);border-radius:5px;color:var(--faint);font:10px var(--mono)}.row-actions{display:flex;gap:7px;justify-content:flex-end}
    .empty{padding:46px 22px;text-align:center}.empty-icon{display:grid;place-items:center;width:42px;height:42px;margin:0 auto 14px;border:1px solid var(--border);border-radius:11px;background:var(--accent-dim);color:var(--muted)}.empty-icon svg{width:19px}.empty strong{display:block;font-size:14px;margin-bottom:5px}.empty p{color:var(--muted);font-size:12px}.loading{padding:26px 22px;color:var(--muted);font:12px var(--mono)}
    .alert{display:none;margin:0 0 16px;padding:12px 14px;border:1px solid rgba(255,122,122,.24);border-radius:9px;background:var(--danger-dim);color:#ffb0b0;font-size:12px}.alert.show{display:block}.toast{position:fixed;left:50%;bottom:26px;z-index:50;max-width:calc(100% - 32px);padding:10px 15px;border:1px solid var(--accent-border);border-radius:9px;background:#181716;color:var(--accent);box-shadow:0 16px 48px rgba(0,0,0,.5);font:12px var(--mono);opacity:0;pointer-events:none;transform:translate(-50%,16px);transition:opacity .22s,transform .22s}.toast.show{opacity:1;transform:translate(-50%,0)}
    @media(max-width:860px){.layout{grid-template-columns:1fr}.flow-card{order:-1}.flow{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.flow-title,.notice{grid-column:1/-1}.flow-step{padding:0 8px 0 22px}.flow-step::before{display:none}.origin-item{grid-template-columns:1fr auto}.route{grid-column:1/-1;grid-row:2}.row-actions{grid-column:2;grid-row:1/3}}
    @media(max-width:640px){.topbar-inner,.page{width:min(100% - 28px,1180px)}.guard{display:none}.page{padding:38px 0 54px}.hero{margin-bottom:24px}.hero p{font-size:14px}.form-grid{grid-template-columns:1fr}.field-wide{grid-column:auto}.card-head,.card-body,.flow{padding:18px}.flow{display:block}.flow-step{padding:0 0 16px 28px}.flow-step::before{display:block}.origin-item{display:block;padding:16px 12px}.route{margin-top:13px;align-items:flex-start;flex-wrap:wrap}.row-actions{margin-top:14px;justify-content:flex-start}.row-actions .btn{flex:1}.list-head-actions{align-items:flex-end;flex-direction:column}.list-head-actions .btn{min-height:36px}.stub-control{align-items:center}.actions .btn{flex:1}.toast{bottom:18px}}
    @media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;transition:none!important}}
  </style>
</head>
<body>
  <header class="topbar"><div class="topbar-inner">
    <div class="brand"><span class="mark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg></span><b>xhttp</b><span>.manager</span></div>
    <div class="top-actions"><div class="guard"><span class="guard-dot"></span>проверка nginx включена</div><form method="post" action="__PATH__/logout"><button class="btn ghost small" type="submit">Выйти</button></form></div>
  </div></header>

  <main class="page">
    <section class="hero"><div class="eyebrow">Маршрутизация</div><h1>XHTTP Manager<em>.</em></h1><p>Управляйте origin-доменами и направляйте XHTTP-запросы на локальные порты Xray. Каждое изменение проверяется nginx перед применением.</p></section>

    <div id="alert" class="alert" role="alert"></div>
    <section class="layout" aria-label="Настройка маршрута">
      <div class="card">
        <div class="card-head"><div><h2 id="formTitle" class="card-title">Новый origin</h2><p class="card-desc">Заполните адрес назначения и сохраните маршрут.</p></div><span id="editBadge" class="count" hidden>редактирование</span></div>
        <div class="card-body">
          <form id="originForm">
            <div class="form-grid">
              <div class="field"><label for="domain">Origin-домен</label><input id="domain" name="domain" type="text" placeholder="origin.example.com" autocomplete="off" required><span class="hint">Без протокола и порта</span></div>
              <div class="field"><label for="path">XHTTP-путь</label><input id="path" name="path" type="text" value="/xhttp" autocomplete="off" required><span class="hint">Например, <span class="mono">/xhttp</span></span></div>
              <div class="field"><label for="port">Порт Xray</label><input id="port" name="port" type="number" min="1" max="65535" value="10086" required><span class="hint">Только localhost</span></div>
              <div class="field field-wide">
                <div class="stub-control">
                  <div class="stub-copy"><strong>Сайт-заглушка</strong><span>Показывать обычный сайт для запросов вне XHTTP-пути. Если выключено, nginx вернёт 404.</span></div>
                  <label class="switch" aria-label="Включить сайт-заглушку"><input id="stubEnabled" name="stub_enabled" type="checkbox"><span class="track"></span></label>
                </div>
                <div id="stubPath" class="stub-path is-disabled"><label for="stubRoot">Каталог сайта-заглушки</label><input id="stubRoot" name="stub_root" type="text" placeholder="/var/www/stub" autocomplete="off" disabled><span class="hint">Абсолютный Linux-путь, доступный пользователю nginx</span></div>
              </div>
            </div>
            <div class="actions"><button id="saveButton" class="btn primary" type="submit"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg><span id="saveLabel">Создать origin</span></button><button id="cancelButton" class="btn ghost" type="button" hidden>Отменить</button></div>
          </form>
        </div>
      </div>

      <aside class="card flow-card"><div class="flow"><div class="flow-title">Как идёт запрос</div><div class="flow-step current"><span class="flow-dot"></span><strong>Клиент / CDN</strong>Запрос приходит на origin-домен.</div><div class="flow-step"><span class="flow-dot"></span><strong>nginx :80</strong>Сверяет домен и точный XHTTP-путь.</div><div class="flow-step"><span class="flow-dot"></span><strong>Локальный Xray</strong><code>127.0.0.1:&lt;порт&gt;</code></div><div class="notice"><strong>Безопасное применение:</strong> конфигурация активируется только после успешного <span class="mono">nginx -t</span>.</div></div></aside>
    </section>

    <section class="card list-card" aria-labelledby="originsTitle">
      <div class="card-head"><div><h2 id="originsTitle" class="card-title">Активные origin</h2><p class="card-desc">Маршруты, которыми сейчас управляет панель.</p></div><div class="list-head-actions"><span id="originCount" class="count">0</span><button id="rollbackButton" class="btn danger small" type="button"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>Откатить изменение</button></div></div>
      <div id="originList" class="origin-list" aria-live="polite" aria-busy="true"><div class="loading">Загрузка маршрутов…</div></div>
    </section>
  </main>
  <div id="toast" class="toast" role="status" aria-live="polite"></div>

  <script>
    const P='__PATH__';
    const el=id=>document.getElementById(id);
    const form=el('originForm'), list=el('originList'), alertBox=el('alert'), stubEnabled=el('stubEnabled'), stubRoot=el('stubRoot'), stubPath=el('stubPath');
    let origins=[], editing=null, toastTimer=0;
    const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

    async function api(url, options={}){
      const response=await fetch(P+'/api/'+url,options);
      const text=await response.text();
      let payload=null;
      try{payload=text?JSON.parse(text):null}catch{payload=text}
      if(response.status===401){location.href=P+'/login';throw new Error('Требуется повторный вход.')}
      if(!response.ok)throw new Error(payload?.detail||payload||'Не удалось выполнить запрос.');
      return payload;
    }
    function showError(message=''){alertBox.textContent=message;alertBox.classList.toggle('show',Boolean(message));if(message)alertBox.scrollIntoView({behavior:'smooth',block:'center'})}
    function toast(message){clearTimeout(toastTimer);el('toast').textContent=message;el('toast').classList.add('show');toastTimer=setTimeout(()=>el('toast').classList.remove('show'),2200)}
    function toggleStub(){const enabled=stubEnabled.checked;stubRoot.disabled=!enabled;stubRoot.required=enabled;stubPath.classList.toggle('is-disabled',!enabled)}
    function setBusy(button,busy,label){button.disabled=busy;if(label)button.querySelector('span')?button.querySelector('span').textContent=label:button.textContent=label}

    function render(){
      el('originCount').textContent=String(origins.length);
      list.setAttribute('aria-busy','false');
      if(!origins.length){list.innerHTML='<div class="empty"><span class="empty-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v6m0 8v6M4.93 4.93l4.24 4.24m5.66 5.66 4.24 4.24M2 12h6m8 0h6M4.93 19.07l4.24-4.24m5.66-5.66 4.24-4.24"/></svg></span><strong>Маршрутов пока нет</strong><p>Создайте первый origin в форме выше.</p></div>';return}
      list.innerHTML=origins.map(item=>`<article class="origin-item"><div class="origin-domain"><div class="domain-line"><span class="live-dot"></span>${esc(item.domain)}</div><div class="route-meta">origin · HTTP/80</div></div><div><div class="route"><code>${esc(item.path)}</code><span class="arrow">→</span><code>127.0.0.1:${item.port}</code></div><span class="tag">${item.stub_enabled?'заглушка: '+esc(item.stub_root):'остальные запросы: 404'}</span></div><div class="row-actions"><button class="btn ghost small" type="button" onclick="editOrigin('${item.id}')">Изменить</button><button class="btn danger small" type="button" onclick="deleteOrigin('${item.id}')">Удалить</button></div></article>`).join('');
    }
    async function load(){list.setAttribute('aria-busy','true');try{origins=await api('origins');render()}catch(error){showError(error.message);list.innerHTML='<div class="loading">Не удалось загрузить маршруты.</div>'}}
    function resetForm(){editing=null;form.reset();el('path').value='/xhttp';el('port').value='10086';el('formTitle').textContent='Новый origin';el('editBadge').hidden=true;el('cancelButton').hidden=true;el('saveLabel').textContent='Создать origin';toggleStub();showError()}
    function editOrigin(id){const item=origins.find(origin=>origin.id===id);if(!item)return;editing=id;el('domain').value=item.domain;el('path').value=item.path;el('port').value=item.port;stubEnabled.checked=item.stub_enabled;stubRoot.value=item.stub_root||'';el('formTitle').textContent='Изменить origin';el('editBadge').hidden=false;el('cancelButton').hidden=false;el('saveLabel').textContent='Сохранить изменения';toggleStub();showError();form.scrollIntoView({behavior:'smooth',block:'center'});el('domain').focus()}
    form.addEventListener('submit',async event=>{event.preventDefault();showError();const payload=Object.fromEntries(new FormData(form));payload.port=Number(payload.port);payload.stub_enabled=stubEnabled.checked;if(!payload.stub_enabled)payload.stub_root=null;const button=el('saveButton'),label=el('saveLabel'),oldLabel=label.textContent;button.disabled=true;label.textContent='Применяем…';try{await api('origins'+(editing?'/'+editing:''),{method:editing?'PUT':'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});toast(editing?'Origin обновлён':'Origin создан');resetForm();await load()}catch(error){showError(error.message)}finally{button.disabled=false;if(label.textContent==='Применяем…')label.textContent=oldLabel}});
    async function deleteOrigin(id){const item=origins.find(origin=>origin.id===id);if(!item||!confirm(`Удалить маршрут ${item.domain}?`))return;showError();try{await api('origins/'+id,{method:'DELETE'});toast('Origin удалён');if(editing===id)resetForm();await load()}catch(error){showError(error.message)}}
    async function rollback(){if(!confirm('Вернуть предыдущую ревизию nginx-конфигурации?'))return;const button=el('rollbackButton');button.disabled=true;showError();try{const result=await api('rollback',{method:'POST'});toast('Выполнен откат: '+result.revision);resetForm();await load()}catch(error){showError(error.message)}finally{button.disabled=false}}
    stubEnabled.addEventListener('change',toggleStub);el('cancelButton').addEventListener('click',resetForm);el('rollbackButton').addEventListener('click',rollback);toggleStub();load();
  </script>
</body>
</html>'''
