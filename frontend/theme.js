/* ============================================================
   主题切换逻辑（暗色 / 浅色 / 护眼）— index.html 与 detail.html 共用
   ------------------------------------------------------------
   - 持久化：localStorage key = "theme"
   - 三态下拉：<select id="themeSelect">，自动填充选项
   - 图表跟随：页面可注册 window.__themeOnChange = fn，
     切换时自动调用（详情页用它重绘 Chart.js）
   ============================================================ */
(function () {
    var THEMES = [
        { id: "dark",  name: "暗色" },
        { id: "light", name: "浅色" },
        { id: "eye",   name: "护眼" }
    ];
    var STORAGE_KEY = "theme";
    var DEFAULT_THEME = "dark";

    function readSaved() {
        try {
            var v = localStorage.getItem(STORAGE_KEY);
            return THEMES.some(function (t) { return t.id === v; }) ? v : DEFAULT_THEME;
        } catch (e) { return DEFAULT_THEME; }
    }

    /** 应用主题：写 data-theme 属性 + 持久化 */
    function applyTheme(name) {
        if (!THEMES.some(function (t) { return t.id === name; })) name = DEFAULT_THEME;
        document.documentElement.setAttribute("data-theme", name);
        try { localStorage.setItem(STORAGE_KEY, name); } catch (e) {}
        // 同步已存在的下拉
        var sel = document.getElementById("themeSelect");
        if (sel && sel.value !== name) sel.value = name;
        // 通知页面（详情页重绘图表）
        if (typeof window.__themeOnChange === "function") {
            try { window.__themeOnChange(name); } catch (e) {}
        }
    }

    /** 读取图表配色（供 Chart.js 使用），未定义时回退暗色值 */
    function getChartColors() {
        var cs = getComputedStyle(document.documentElement);
        function v(name, fallback) {
            var val = cs.getPropertyValue(name);
            val = val ? val.trim() : "";
            return val || fallback;
        }
        return {
            line:      v("--chart-line", "#66c0f4"),
            lineFill:  v("--chart-line-fill", "rgba(102,192,244,.08)"),
            lineSoft:  v("--chart-line-soft", "rgba(102,192,244,.25)"),
            ema7:      v("--chart-ema7", "#4ade80"),
            ema30:     v("--chart-ema30", "#e6b450"),
            grid:      v("--chart-grid", "#1e2730"),
            tick:      v("--chart-tick", "#62707e"),
            legend:    v("--chart-legend", "#8d9aa7")
        };
    }

    /** 初始化下拉：填充选项、回显当前主题、绑定切换 */
    function initThemeSelect() {
        var sel = document.getElementById("themeSelect");
        if (!sel) return;
        if (!sel.options.length) {
            THEMES.forEach(function (t) {
                var o = document.createElement("option");
                o.value = t.id;
                o.textContent = t.name;
                sel.appendChild(o);
            });
        }
        sel.value = readSaved();
        sel.addEventListener("change", function () { applyTheme(sel.value); });
    }

    /** 页面脚本应在 DOM 就绪后调用 */
    function initTheme() {
        initThemeSelect();
    }

    // 暴露
    window.ThemeAPI = {
        applyTheme: applyTheme,
        getChartColors: getChartColors,
        initTheme: initTheme,
        current: readSaved
    };
})();
