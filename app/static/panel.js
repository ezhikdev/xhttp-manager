"use strict";
const $ = (id) => document.getElementById(id);
const P = document.querySelector('meta[name="panel-path"]').content;
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
let domains = [],
  editing = null,
  policy = { rules: [], trusted_interfaces: [] };
let pending = null,
  confirmationToken = null,
  timer = null,
  dirty = false;
const titles = {
  overview: "Обзор",
  domains: "Домены и пути",
  firewall: "Firewall",
  settings: "Настройки",
};

async function api(path, method = "GET", body) {
  const response = await fetch(P + "/api/" + path, {
    method,
    credentials: "same-origin",
    signal: AbortSignal.timeout(45000),
    headers: {
      "X-CSRF-Token": csrf,
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw Error(
      "Сервер вернул некорректный ответ. Проверьте состояние сервиса.",
    );
  }
  if (response.status === 401) {
    location.assign(P + "/login");
    throw Error("Требуется повторный вход.");
  }
  if (!response.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail || data),
    );
  return data;
}
function error(message = "") {
  $("alert").textContent = message;
  $("alert").hidden = !message;
  if (message)
    $("alert").scrollIntoView({ block: "center", behavior: "smooth" });
}
let toastTimeout;
function toast(message) {
  clearTimeout(toastTimeout);
  $("toast").textContent = message;
  $("toast").hidden = false;
  toastTimeout = setTimeout(() => {
    $("toast").hidden = true;
  }, 4000);
}
async function busy(button, task) {
  if (button.disabled) return;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  error();
  try {
    await task();
  } catch (e) {
    error(e.message || "Не удалось выполнить действие.");
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}
function showTab(name) {
  if (!titles[name]) name = "overview";
  document.querySelectorAll(".view").forEach((view) => {
    view.hidden = view.id !== "view-" + name;
  });
  document.querySelectorAll("[data-tab]").forEach((link) => {
    link.classList.toggle("active", link.dataset.tab === name);
    if (link.dataset.tab === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $("breadcrumb").textContent = "Инфраструктура / " + titles[name];
  document.title = titles[name] + " · XHTTP Manager";
}
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
document.querySelectorAll("[data-go]").forEach((button) =>
  button.addEventListener("click", () => {
    location.hash = button.dataset.go;
    showTab(button.dataset.go);
    if (button.dataset.go === "domains") $("domainName").focus();
  }),
);
showTab(location.hash.slice(1));
try {
  document.documentElement.dataset.theme =
    localStorage.getItem("xhttp-theme") || "dark";
} catch {}
function themeLabel() {
  $("themeButton").textContent =
    document.documentElement.dataset.theme === "dark"
      ? "Светлая тема"
      : "Тёмная тема";
}
themeLabel();
function toggleTheme() {
  const theme =
    document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("xhttp-theme", theme);
  } catch {}
  themeLabel();
}
$("themeButton").addEventListener("click", toggleTheme);
$("mobileTheme").addEventListener("click", toggleTheme);
function pathRow(path = "/xhttp", port = 10086) {
  const row = document.createElement("div");
  row.className = "path-row";
  row.innerHTML =
    '<input class="route-path" aria-label="XHTTP-путь" placeholder="/xhttp" maxlength="512" required value="' +
    esc(path) +
    '"><input class="route-port" type="number" aria-label="Локальный порт Xray" min="1" max="65535" required value="' +
    esc(port) +
    '"><button type="button" class="text-button remove-path" aria-label="Удалить путь">×</button>';
  row.querySelector(".remove-path").addEventListener("click", () => {
    if ($("pathRows").children.length === 1) {
      error("У домена должен остаться хотя бы один путь.");
      return;
    }
    row.remove();
  });
  $("pathRows").append(row);
}
$("addPath").addEventListener("click", () => {
  pathRow(
    "",
    $("pathRows").lastChild?.querySelector(".route-port").value || 10086,
  );
  $("pathRows").lastChild.querySelector("input").focus();
});
function toggleStub() {
  $("stubRoot").disabled = !$("stubEnabled").checked;
  $("stubRoot").required = $("stubEnabled").checked;
}
$("stubEnabled").addEventListener("change", toggleStub);
function resetDomain() {
  editing = null;
  $("domainForm").reset();
  $("pathRows").replaceChildren();
  pathRow();
  $("formTitle").textContent = "Новый домен";
  $("cancelDomain").hidden = true;
  toggleStub();
}
resetDomain();
$("cancelDomain").addEventListener("click", resetDomain);
function domainMarkup(domain, actions = true) {
  return (
    '<article class="domain-item"><div class="domain-info"><div class="domain-name">' +
    esc(domain.domain) +
    '</div><div class="paths">' +
    domain.paths
      .map(
        (route) =>
          '<span class="path-tag">' +
          esc(route.path) +
          " → :" +
          route.port +
          "</span>",
      )
      .join("") +
    '</div><p class="domain-meta">' +
    (domain.stub_enabled
      ? "Заглушка · " + esc(domain.stub_root)
      : "Вне маршрутов · 404") +
    "</p></div>" +
    (actions
      ? '<div class="row-actions"><button class="secondary edit-domain" data-domain="' +
        esc(domain.domain) +
        '">Изменить</button><button class="danger delete-domain" data-domain="' +
        esc(domain.domain) +
        '">Удалить</button></div>'
      : "") +
    "</article>"
  );
}
function renderDomains() {
  const query = $("searchDomains").value.trim().toLowerCase();
  const mode = $("sortDomains").value;
  const sorted = domains
    .filter(
      (d) =>
        d.domain.includes(query) ||
        d.paths.some((p) => p.path.toLowerCase().includes(query)),
    )
    .sort((a, b) =>
      mode === "name"
        ? a.domain.localeCompare(b.domain)
        : (Date.parse(a.created_at) - Date.parse(b.created_at)) *
          (mode === "new" ? -1 : 1),
    );
  $("domainList").innerHTML = sorted.length
    ? sorted.map((d) => domainMarkup(d)).join("")
    : '<div class="empty"><strong>' +
      (query ? "Ничего не найдено" : "Добавьте первый домен") +
      "</strong>" +
      (query
        ? "Попробуйте другой запрос."
        : "Укажите домен и пути в форме рядом.") +
      "</div>";
  $("overviewDomains").innerHTML = domains.length
    ? domains
        .slice(0, 5)
        .map((d) => domainMarkup(d, false))
        .join("")
    : '<div class="empty"><strong>Здесь появятся ваши домены</strong>Откройте «Домены и пути», чтобы добавить первую запись.</div>';
  $("domainCount").textContent = domains.length;
  $("navCount").textContent = domains.length;
  $("statDomains").textContent = domains.length;
  $("statPaths").textContent = domains.reduce((n, d) => n + d.paths.length, 0);
}
async function loadDomains() {
  domains = await api("domains");
  renderDomains();
}
$("searchDomains").addEventListener("input", renderDomains);
$("sortDomains").addEventListener("change", renderDomains);
$("domainList").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-domain]");
  if (!button) return;
  const domain = domains.find((d) => d.domain === button.dataset.domain);
  if (!domain) return;
  if (button.classList.contains("edit-domain")) {
    editing = domain.domain;
    $("domainName").value = domain.domain;
    $("pathRows").replaceChildren();
    domain.paths.forEach((route) => pathRow(route.path, route.port));
    $("stubEnabled").checked = domain.stub_enabled;
    $("stubRoot").value = domain.stub_root || "";
    toggleStub();
    $("formTitle").textContent = "Редактирование домена";
    $("cancelDomain").hidden = false;
    $("domainName").focus();
    return;
  }
  if (!confirm("Удалить домен " + domain.domain + " и все его пути?")) return;
  await busy(button, async () => {
    await api("domains/" + encodeURIComponent(domain.domain), "DELETE");
    if (editing === domain.domain) resetDomain();
    await Promise.all([loadDomains(), loadSystem()]);
    toast("Домен удалён. nginx обновлён.");
  });
});
$("domainForm").addEventListener("submit", (event) => {
  event.preventDefault();
  busy($("saveDomain"), async () => {
    const payload = {
      domain: $("domainName").value.trim(),
      paths: [...$("pathRows").children].map((row) => ({
        path: row.querySelector(".route-path").value.trim(),
        port: Number(row.querySelector(".route-port").value),
      })),
      stub_enabled: $("stubEnabled").checked,
      stub_root: $("stubEnabled").checked ? $("stubRoot").value.trim() : null,
    };
    await api(
      editing ? "domains/" + encodeURIComponent(editing) : "domains",
      editing ? "PUT" : "POST",
      payload,
    );
    resetDomain();
    await Promise.all([loadDomains(), loadSystem()]);
    toast("Домен сохранён. Конфигурация nginx проверена.");
  });
});
$("rollbackButton").addEventListener("click", () => {
  if (
    !confirm(
      "Вернуть маршруты из предыдущей ревизии? Адрес панели останется текущим.",
    )
  )
    return;
  busy($("rollbackButton"), async () => {
    await api("rollback", "POST");
    resetDomain();
    await Promise.all([loadDomains(), loadSystem()]);
    toast("Предыдущие маршруты восстановлены.");
  });
});
async function loadSystem() {
  const state = await api("system");
  $("nginxState").textContent = state.nginx_validation
    ? "Проверка при сохранении"
    : "Тестовый режим";
  $("loadState").textContent = state.load.length
    ? state.load.map((x) => x.toFixed(2)).join(" / ")
    : "Недоступно";
  $("diskState").textContent =
    (state.disk_free / 1024 ** 3).toFixed(1) +
    " / " +
    (state.disk_total / 1024 ** 3).toFixed(1) +
    " ГБ";
  $("revisionState").textContent = state.revision || "Нет ревизий";
}
$("refreshSystem").addEventListener("click", () =>
  busy($("refreshSystem"), loadSystem),
);
function markDirty() {
  dirty = true;
  $("draftState").textContent = "Есть неприменённые изменения";
}
function renderRules() {
  const rules = new Map(
    [22, 80, 443, 2222].map((port) => [
      "tcp:" + port,
      {
        port,
        protocol: "tcp",
        action: "allow",
        sources: [],
        note: "По умолчанию",
        default: true,
      },
    ]),
  );
  policy.rules.forEach((rule) =>
    rules.set(rule.protocol + ":" + rule.port, rule),
  );
  $("ruleRows").innerHTML = [...rules.values()]
    .sort((a, b) => a.port - b.port || a.protocol.localeCompare(b.protocol))
    .map(
      (rule) =>
        "<tr><td><code>" +
        rule.port +
        '</code><span class="caption">' +
        esc(rule.protocol.toUpperCase()) +
        '</span></td><td><span class="' +
        (rule.action === "deny" ? "denied" : "allowed") +
        '">' +
        (rule.action === "deny"
          ? "Закрыт"
          : rule.sources.length
            ? "Белый список"
            : "Все IP") +
        '</span><span class="caption">' +
        esc(rule.sources.join(", ") || rule.note || "") +
        '</span></td><td><div class="row-actions"><button class="text-button edit-rule" data-key="' +
        rule.protocol +
        ":" +
        rule.port +
        '">Изменить</button>' +
        (!rule.default
          ? '<button class="text-button reset-rule" data-key="' +
            rule.protocol +
            ":" +
            rule.port +
            '">Сбросить</button>'
          : "") +
        "</div></td></tr>",
    )
    .join("");
}
$("ruleRows").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-key]");
  if (!button) return;
  const [protocol, p] = button.dataset.key.split(":"),
    port = Number(p);
  if (button.classList.contains("reset-rule")) {
    policy.rules = policy.rules.filter(
      (r) => r.protocol !== protocol || r.port !== port,
    );
    markDirty();
    renderRules();
    return;
  }
  const rule = policy.rules.find(
    (r) => r.protocol === protocol && r.port === port,
  ) || { port, protocol, action: "allow", sources: [], note: "" };
  $("rulePort").value = port;
  $("ruleProtocol").value = protocol;
  $("ruleAction").value = rule.action;
  $("ruleSources").value = rule.sources.join("\n");
  $("ruleNote").value = rule.note;
  toggleSources();
  $("rulePort").focus();
});
function toggleSources() {
  $("ruleSources").disabled = $("ruleAction").value === "deny";
}
$("ruleAction").addEventListener("change", toggleSources);
$("firewallForm").addEventListener("submit", (event) => {
  event.preventDefault();
  busy($("saveRule"), async () => {
    const rule = {
      port: Number($("rulePort").value),
      protocol: $("ruleProtocol").value,
      action: $("ruleAction").value,
      sources:
        $("ruleAction").value === "deny"
          ? []
          : $("ruleSources")
              .value.split(/[\s,;]+/)
              .filter(Boolean),
      note: $("ruleNote").value,
    };
    const next = {
      ...policy,
      rules: [
        ...policy.rules.filter(
          (r) => r.port !== rule.port || r.protocol !== rule.protocol,
        ),
        rule,
      ],
    };
    const checked = await api("firewall/preview", "POST", next);
    policy = checked.policy;
    markDirty();
    renderRules();
    toast("Правило добавлено в изменения. Нажмите «Применить правила».");
  });
});
$("trustedInterfaces").addEventListener("input", markDirty);
function draft() {
  policy.trusted_interfaces = $("trustedInterfaces")
    .value.split(/[\s,;]+/)
    .filter(Boolean);
  return policy;
}
function pendingUI() {
  clearInterval(timer);
  $("pendingBanner").hidden = !pending;
  $("confirmFirewall").hidden = !confirmationToken;
  if (!pending) return;
  pending.clientDeadline = Date.now() / 1000 + pending.remaining;
  const tick = () => {
    const seconds = Math.max(
      0,
      Math.ceil(pending.clientDeadline - Date.now() / 1000),
    );
    $("pendingText").textContent =
      seconds > 0
        ? "Подтвердите доступ. Автоматический откат через " + seconds + " сек."
        : "Срок подтверждения истёк. Восстанавливаем прежние правила…";
    if (!seconds) {
      clearInterval(timer);
      confirmationToken = null;
      setTimeout(() => loadFirewall().catch((e) => error(e.message)), 1500);
    }
  };
  tick();
  timer = setInterval(tick, 1000);
}
async function loadFirewall() {
  try {
    const state = await api("firewall");
    policy = state.policy;
    pending = state.pending;
    confirmationToken = pending?.token || null;
    $("firewallBadge").textContent = pending
      ? "Ожидает подтверждения"
      : state.active
        ? "Активен"
        : "Не включён";
    $("statFirewall").textContent = pending
      ? "Проверка"
      : state.active
        ? "Активен"
        : "Не включён";
    $("statFirewallHint").textContent = state.active
      ? "nftables · входящий трафик"
      : "Первое применение включит фильтрацию";
    $("trustedInterfaces").value = policy.trusted_interfaces.join(", ");
    dirty = false;
    $("draftState").textContent = "Сохранённая конфигурация";
    renderRules();
    pendingUI();
  } catch (e) {
    $("statFirewall").textContent = "Недоступен";
    $("statFirewallHint").textContent = "Проверьте установку helper";
    $("firewallBadge").textContent = "Helper недоступен";
    renderRules();
    throw e;
  }
}
$("reloadFirewall").addEventListener("click", () => {
  if (dirty && !confirm("Сбросить неприменённые изменения?")) return;
  busy($("reloadFirewall"), loadFirewall);
});
$("previewFirewall").addEventListener("click", () =>
  busy($("previewFirewall"), async () => {
    const result = await api("firewall/preview", "POST", draft());
    $("rulesPreview").textContent = result.ruleset;
    $("rulesPreview").hidden = false;
  }),
);
$("applyFirewall").addEventListener("click", () => {
  if (
    !confirm(
      "Применить входящую фильтрацию? Все порты без разрешения будут закрыты. Подтвердите связь в течение 120 секунд.",
    )
  )
    return;
  busy($("applyFirewall"), async () => {
    const result = await api("firewall", "PUT", draft());
    pending = result;
    confirmationToken = result.token;
    $("firewallBadge").textContent = "Ожидает подтверждения";
    $("draftState").textContent = "Ожидает подтверждения";
    pendingUI();
    $("pendingBanner").scrollIntoView({ block: "center", behavior: "smooth" });
  });
});
$("confirmFirewall").addEventListener("click", () =>
  busy($("confirmFirewall"), async () => {
    await api("firewall/confirm", "POST", { token: confirmationToken });
    confirmationToken = null;
    await loadFirewall();
    toast("Правила подтверждены. Они сохранятся после перезагрузки.");
  }),
);
$("cancelFirewall").addEventListener("click", () =>
  busy($("cancelFirewall"), async () => {
    await api("firewall/cancel", "POST");
    confirmationToken = null;
    await loadFirewall();
    toast("Предыдущие правила восстановлены.");
  }),
);
async function loadSettings() {
  const value = await api("settings");
  $("currentPath").value = value.panel_path;
  $("settingsUser").textContent = value.user;
}
$("settingsForm").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!confirm("Сменить адрес панели? Сохраните новый URL после перехода."))
    return;
  busy($("rotatePath"), async () => {
    const value = await api("settings/path", "PUT", {
      path: $("newPath").value.trim() || null,
    });
    location.assign(value.panel_path + "#settings");
  });
});
window.addEventListener("beforeunload", (event) => {
  if (dirty || pending) {
    event.preventDefault();
    event.returnValue = "";
  }
});
Promise.allSettled([
  loadDomains(),
  loadSystem(),
  loadSettings(),
  loadFirewall(),
]).then((results) => {
  const errors = results
    .filter((result) => result.status === "rejected")
    .map((result) => result.reason.message);
  if (errors.length) error(errors.join("\n"));
});
