(function () {
  "use strict";

  var DENSITY_KEY = "scm_density_mode";
  var TOAST_TIMEOUT = 2800;

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function qsa(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function normalizeText(v) {
    return (v || "").replace(/\s+/g, " ").trim();
  }

  function createToastEl() {
    var toast = qs("#toast");
    if (toast) {
      return toast;
    }
    toast = document.createElement("div");
    toast.id = "toast";
    toast.className = "toast";
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");

    var title = document.createElement("div");
    title.className = "title";
    title.textContent = "提示";

    var msg = document.createElement("div");
    msg.className = "msg";

    toast.appendChild(title);
    toast.appendChild(msg);
    document.body.appendChild(toast);
    return toast;
  }

  function showToast(title, msg) {
    var toast = createToastEl();
    var titleEl = qs(".title", toast);
    var msgEl = qs(".msg", toast);
    if (titleEl) {
      titleEl.textContent = normalizeText(title) || "提示";
    }
    if (msgEl) {
      msgEl.textContent = normalizeText(msg);
    }

    toast.classList.add("show");
    window.clearTimeout(toast.__timer);
    toast.__timer = window.setTimeout(function () {
      toast.classList.remove("show");
    }, TOAST_TIMEOUT);
  }

  async function copyText(text) {
    var value = text == null ? "" : String(text);
    if (!value) {
      showToast("复制失败", "没有可复制的内容");
      return;
    }

    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        var ta = document.createElement("textarea");
        ta.value = value;
        ta.setAttribute("readonly", "readonly");
        ta.style.position = "fixed";
        ta.style.top = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      showToast("复制成功", "内容已复制到剪贴板");
    } catch (err) {
      showToast("复制失败", "浏览器未授予剪贴板权限");
    }
  }

  function applyDensity(mode) {
    var body = document.body;
    var safeMode = mode === "compact" ? "compact" : "cozy";
    body.classList.toggle("density-compact", safeMode === "compact");

    qsa("[data-density-label]").forEach(function (el) {
      el.textContent = safeMode === "compact" ? "切换为舒适" : "切换为紧凑";
    });

    try {
      localStorage.setItem(DENSITY_KEY, safeMode);
    } catch (e) {
      return;
    }
  }

  function loadDensity() {
    try {
      return localStorage.getItem(DENSITY_KEY) || "cozy";
    } catch (e) {
      return "cozy";
    }
  }

  function initDensityToggle() {
    applyDensity(loadDensity());
    qsa("[data-density-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var compact = document.body.classList.contains("density-compact");
        applyDensity(compact ? "cozy" : "compact");
      });
    });
  }

  function ensureOfflineBanner() {
    var el = qs("#offline-banner");
    if (el) {
      return el;
    }

    el = document.createElement("div");
    el.id = "offline-banner";
    el.className = "offline-banner";
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    el.textContent = "当前处于离线状态，网络请求可能失败";
    document.body.appendChild(el);
    return el;
  }

  function initOnlineState() {
    var banner = ensureOfflineBanner();

    function refresh() {
      if (navigator.onLine) {
        if (banner.classList.contains("show")) {
          showToast("网络恢复", "已重新连接网络");
        }
        banner.classList.remove("show");
      } else {
        banner.classList.add("show");
      }
    }

    refresh();
    window.addEventListener("online", refresh, { passive: true });
    window.addEventListener("offline", refresh, { passive: true });
  }

  function trimField(field) {
    if (!field || typeof field.value !== "string") {
      return;
    }
    if (field.type === "password") {
      return;
    }
    field.value = field.value.trim();
  }

  function setFieldValidity(field) {
    if (!field || typeof field.setCustomValidity !== "function") {
      return true;
    }

    trimField(field);
    var value = (field.value || "").trim();
    var message = "";

    if (field.hasAttribute("data-validate-url") && value) {
      if (!/^https?:\/\/\S+$/i.test(value)) {
        message = "请输入合法 URL（http/https）";
      }
    }

    if (!message && field.hasAttribute("data-validate-int") && value) {
      var n = Number(value);
      if (!Number.isFinite(n) || Number.isNaN(n)) {
        message = "请输入有效数字";
      }
    }

    if (!message && field.hasAttribute("data-min")) {
      var min = Number(field.getAttribute("data-min"));
      if (value && Number(value) < min) {
        message = "数值过小";
      }
    }

    if (!message && field.hasAttribute("data-max")) {
      var max = Number(field.getAttribute("data-max"));
      if (value && Number(value) > max) {
        message = "数值过大";
      }
    }

    field.setCustomValidity(message);
    return !message;
  }

  function validateForm(form) {
    var fields = qsa("input,select,textarea", form);
    var ok = true;

    fields.forEach(function (field) {
      if (!setFieldValidity(field)) {
        ok = false;
      }
    });

    if (!ok) {
      return false;
    }

    if (typeof form.reportValidity === "function") {
      return form.reportValidity();
    }

    return true;
  }

  function lockSubmitButtons(form) {
    var buttons = qsa('button[type="submit"],input[type="submit"]', form);
    buttons.forEach(function (btn) {
      if (!btn.dataset.originalText) {
        btn.dataset.originalText = btn.tagName === "INPUT" ? btn.value : btn.textContent;
      }
      btn.disabled = true;
      btn.classList.add("is-loading");
      if (btn.tagName === "INPUT") {
        btn.value = "提交中...";
      } else {
        btn.textContent = "提交中...";
      }
    });
  }

  function unlockSubmitButtons(form) {
    var buttons = qsa('button[type="submit"],input[type="submit"]', form);
    buttons.forEach(function (btn) {
      btn.disabled = false;
      btn.classList.remove("is-loading");
      if (btn.dataset.originalText) {
        if (btn.tagName === "INPUT") {
          btn.value = btn.dataset.originalText;
        } else {
          btn.textContent = btn.dataset.originalText;
        }
      }
    });
    delete form.dataset.submitting;
  }

  function initFormGuards() {
    document.addEventListener(
      "blur",
      function (event) {
        var target = event.target;
        if (!(target instanceof HTMLElement)) {
          return;
        }
        if (target.matches("input,select,textarea")) {
          setFieldValidity(target);
        }
      },
      true
    );

    qsa("form[data-lock-submit]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (event.defaultPrevented) {
          return;
        }
        if (form.dataset.submitting === "1") {
          event.preventDefault();
          return;
        }
        if (!validateForm(form)) {
          event.preventDefault();
          return;
        }

        form.dataset.submitting = "1";
        lockSubmitButtons(form);
      });
    });

    window.addEventListener(
      "pageshow",
      function () {
        qsa("form[data-lock-submit]").forEach(function (form) {
          if (form.dataset.submitting === "1") {
            unlockSubmitButtons(form);
          }
        });
      },
      { passive: true }
    );
  }

  function buildConfirmModal() {
    var backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.setAttribute("aria-hidden", "true");

    var modal = document.createElement("div");
    modal.className = "modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");

    var header = document.createElement("header");
    var title = document.createElement("h3");
    title.textContent = "请确认操作";
    header.appendChild(title);

    var body = document.createElement("div");
    body.className = "body";
    var message = document.createElement("div");
    message.className = "hint";
    message.style.fontSize = "14px";
    body.appendChild(message);

    var footer = document.createElement("footer");
    footer.className = "actions";
    var cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "btn";
    cancelBtn.textContent = "取消";

    var confirmBtn = document.createElement("button");
    confirmBtn.type = "button";
    confirmBtn.className = "btn danger";
    confirmBtn.textContent = "确认";

    footer.appendChild(cancelBtn);
    footer.appendChild(confirmBtn);

    modal.appendChild(header);
    modal.appendChild(body);
    modal.appendChild(footer);
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);

    var state = {
      onConfirm: null,
      lastActive: null,
    };

    function close() {
      backdrop.classList.remove("show");
      backdrop.setAttribute("aria-hidden", "true");
      document.body.classList.remove("modal-open");
      document.removeEventListener("keydown", onKeydown, true);
      if (state.lastActive && typeof state.lastActive.focus === "function") {
        state.lastActive.focus();
      }
    }

    function onKeydown(event) {
      if (!backdrop.classList.contains("show")) {
        return;
      }

      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      var focusables = qsa("button,[href],[tabindex]:not([tabindex='-1'])", modal).filter(function (el) {
        return !el.hasAttribute("disabled");
      });

      if (!focusables.length) {
        event.preventDefault();
        return;
      }

      var first = focusables[0];
      var last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    function open(text, onConfirm) {
      state.lastActive = document.activeElement;
      state.onConfirm = onConfirm;
      message.textContent = normalizeText(text) || "确认继续执行该操作吗？";
      backdrop.classList.add("show");
      backdrop.setAttribute("aria-hidden", "false");
      document.body.classList.add("modal-open");
      document.addEventListener("keydown", onKeydown, true);
      cancelBtn.focus();
    }

    cancelBtn.addEventListener("click", close);
    confirmBtn.addEventListener("click", function () {
      var callback = state.onConfirm;
      close();
      if (typeof callback === "function") {
        callback();
      }
    });

    backdrop.addEventListener("click", function (event) {
      if (event.target === backdrop) {
        close();
      }
    });

    return {
      open: open,
    };
  }

  function initConfirmGuards() {
    var modal = buildConfirmModal();

    document.addEventListener(
      "submit",
      function (event) {
        var form = event.target;
        if (!(form instanceof HTMLFormElement)) {
          return;
        }

        var message = form.getAttribute("data-confirm");
        if (!message) {
          return;
        }

        if (form.dataset.confirmed === "1") {
          delete form.dataset.confirmed;
          return;
        }

        event.preventDefault();
        modal.open(message, function () {
          form.dataset.confirmed = "1";
          if (typeof form.requestSubmit === "function") {
            form.requestSubmit();
          } else {
            form.submit();
          }
        });
      },
      true
    );
  }

  function initCopyTrigger() {
    document.addEventListener("click", function (event) {
      if (!(event.target instanceof Element)) {
        return;
      }

      var btn = event.target.closest("[data-copy],[data-copy-text]");
      if (!btn) {
        return;
      }

      var selector = btn.getAttribute("data-copy");
      var node = selector ? qs(selector) : null;
      var text = "";

      if (node) {
        if (Object.prototype.hasOwnProperty.call(node, "value")) {
          text = node.value;
        } else {
          text = node.textContent || "";
        }
      } else {
        text = btn.getAttribute("data-copy-text") || "";
      }

      copyText(text);
    });
  }

  function isNestedInteractive(node) {
    return Boolean(node.closest("a,button,input,select,textarea,label,summary,details,form"));
  }

  function initRowNavigation() {
    document.addEventListener("click", function (event) {
      var row = event.target.closest("[data-row-link]");
      if (!row || isNestedInteractive(event.target)) {
        return;
      }
      var href = row.getAttribute("data-row-link");
      if (href) {
        window.location.href = href;
      }
    });

    document.addEventListener("keydown", function (event) {
      var row = event.target.closest("[data-row-link]");
      if (!row) {
        return;
      }
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        var href = row.getAttribute("data-row-link");
        if (href) {
          window.location.href = href;
        }
      }
    });
  }

  function rafThrottle(fn) {
    var ticking = false;
    return function () {
      if (ticking) {
        return;
      }
      ticking = true;
      requestAnimationFrame(function () {
        ticking = false;
        fn();
      });
    };
  }

  function initSourceTable() {
    var table = qs("#sources-table");
    if (!table || !table.tBodies || !table.tBodies[0]) {
      return;
    }

    var tbody = table.tBodies[0];
    var rows = qsa("tr.source-row", tbody);
    if (!rows.length) {
      return;
    }

    var searchEl = qs("#source-search");
    var kindEl = qs("#source-kind-filter");
    var sortEl = qs("#source-sort");
    var emptyEl = qs("#source-empty-filter");

    function sortFn(mode) {
      if (mode === "name_asc") {
        return function (a, b) {
          return (a.dataset.name || "").localeCompare(b.dataset.name || "", "zh-CN");
        };
      }
      if (mode === "name_desc") {
        return function (a, b) {
          return (b.dataset.name || "").localeCompare(a.dataset.name || "", "zh-CN");
        };
      }
      if (mode === "updated_asc") {
        return function (a, b) {
          return Number(a.dataset.updated || 0) - Number(b.dataset.updated || 0);
        };
      }
      return function (a, b) {
        return Number(b.dataset.updated || 0) - Number(a.dataset.updated || 0);
      };
    }

    function applyFilterSort() {
      var search = normalizeText(searchEl ? searchEl.value : "").toLowerCase();
      var kind = (kindEl ? kindEl.value : "all").toLowerCase();
      var mode = (sortEl ? sortEl.value : "updated_desc").toLowerCase();

      var visibleRows = rows.filter(function (row) {
        var rowName = (row.dataset.name || "").toLowerCase();
        var rowKind = (row.dataset.kind || "").toLowerCase();

        var passSearch = !search || rowName.indexOf(search) !== -1;
        var passKind = kind === "all" || rowKind === kind;
        var show = passSearch && passKind;

        row.hidden = !show;
        return show;
      });

      visibleRows.sort(sortFn(mode));
      visibleRows.forEach(function (row) {
        tbody.appendChild(row);
      });

      if (emptyEl) {
        emptyEl.hidden = visibleRows.length !== 0;
      }
    }

    var scheduledApply = rafThrottle(applyFilterSort);

    [searchEl, kindEl, sortEl].forEach(function (el) {
      if (!el) {
        return;
      }
      el.addEventListener("input", scheduledApply, { passive: true });
      el.addEventListener("change", scheduledApply, { passive: true });
    });

    window.addEventListener("resize", scheduledApply, { passive: true });
    scheduledApply();
  }

  function initResultTools() {
    var out = qs("#out");
    var wrap = qs("#toggle-wrap");
    if (!out || !wrap) {
      return;
    }

    function sync() {
      out.style.whiteSpace = wrap.checked ? "pre-wrap" : "pre";
      out.style.wordBreak = wrap.checked ? "break-word" : "normal";
    }

    wrap.addEventListener("change", sync, { passive: true });
    sync();
  }

  function consumeToastParam() {
    var params = new URLSearchParams(window.location.search || "");
    var toastText = params.get("toast");
    if (!toastText) {
      return;
    }

    showToast("提示", toastText);
    params.delete("toast");

    var next = window.location.pathname + (params.toString() ? "?" + params.toString() : "") + window.location.hash;
    window.history.replaceState({}, "", next);
  }

  window.__toast = showToast;

  document.addEventListener("DOMContentLoaded", function () {
    initDensityToggle();
    initOnlineState();
    initCopyTrigger();
    initFormGuards();
    initConfirmGuards();
    initRowNavigation();
    initSourceTable();
    initResultTools();
    consumeToastParam();
  });
})();
