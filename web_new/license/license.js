// 授权码查询 - 对接自研授权服务 (https://license.yanyu.cxk-kk.site/api/query)
// 查询: 可导出次数 / 剩余换绑次数 / 到期时间
!function () {
    'use strict';

    // ---------- 授权服务双线路兜底 (2026-09-12) ----------
    // 主: license.yanyu.cxk-kk.site (CF)  备: license-us.yanyu.cxk-kk.site (VPS 中继)
    // 铁律: 仅传输层失败(连接失败/8s 超时)才换线; 拿到任何 HTTP 状态码立即返回, 不重试
    var AUTH_HOSTS = ['https://license.yanyu.cxk-kk.site', 'https://license-us.yanyu.cxk-kk.site'];
    async function relayFetch(path, payload) {
        var lastErr = null;
        for (var i = 0; i < AUTH_HOSTS.length; i++) {
            var ac = new AbortController();
            var timer = setTimeout(function () { ac.abort(); }, 8000);
            try {
                return await fetch(AUTH_HOSTS[i] + path, {
                    method: 'POST',
                    headers: { 'content-type': 'application/json' },
                    cache: 'no-store',
                    body: JSON.stringify(payload),
                    signal: ac.signal
                });
            } catch (e) { lastErr = e; }
            finally { clearTimeout(timer); }
        }
        throw lastErr;
    }
    var input = document.getElementById('licenseCodeQuery');
    var btn = document.getElementById('btnQueryLicense');
    var msgEl = document.getElementById('licenseQueryMessage');
    var result = document.getElementById('licenseQueryResult');
    var exportsEl = document.getElementById('licenseRemainingExports');
    var bindingsEl = document.getElementById('licenseRemainingBindings');
    var daysEl = document.getElementById('licenseRemainingDays');
    var statusEl = document.getElementById('licenseStatusValue');

    var lastHit = 0;
    var busy = false;

    function setMsg(text, isErr) {
        if (!msgEl) return;
        msgEl.hidden = !text;
        msgEl.textContent = text || '';
        msgEl.className = 'license-message' + (isErr ? ' is-error' : '');
    }

    function fmtDate(s) {
        if (!s) return '永久';
        var d = new Date(s);
        if (isNaN(d.getTime())) return String(s);
        function p(n) { return String(n).padStart(2, '0'); }
        return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
    }

    function query() {
        var code = (input && input.value || '').trim();
        if (busy) return;
        if (!code) { setMsg('请输入授权码', true); return; }
        var wait = Math.ceil((lastHit - Date.now()) / 1000);
        if (wait > 0) { setMsg('请等待 ' + wait + ' 秒后再试', true); return; }
        busy = true;
        if (btn) { btn.disabled = true; btn.textContent = '正在查询…'; }
        setMsg('');
        relayFetch('/api/query', { code: code }).then(function (r) { return r.json(); }).then(function (j) {
            busy = false;
            if (btn) { btn.disabled = false; btn.textContent = '查询授权码'; }
            lastHit = Date.now() + 3000;
            if (!j || !j.valid) { setMsg('查询失败，请稍后重试', true); return; }
            if (!j.found) { setMsg('授权码无效，请检查后重试。', true); if (result) result.hidden = true; return; }
            // 状态语义: unused=有效未激活(可直接用于网页转换/首页导入) active=使用中 disabled=已禁用
            // 到期判定以 expires_at 为准, 与 status 解耦 (status 不再翻转的旧码也正确显示)
            var expired = !!(j.expiresAt && new Date(j.expiresAt).getTime() < Date.now());
            var statusText = '未知';
            var statusIsErr = false;
            if (j.status === 'disabled') { statusText = '已禁用'; statusIsErr = true; }
            else if (expired) { statusText = '已到期'; statusIsErr = true; }
            else if (j.status === 'active') { statusText = '使用中'; }
            else if (j.status === 'unused') { statusText = '有效 · 未激活使用'; }
            if (statusEl) statusEl.textContent = statusText;
            if (!j.active && statusIsErr) {
                setMsg('该授权码当前不可用（' + statusText + '）。', true);
            } else {
                setMsg('', false);
            }
            if (result) result.hidden = false;
            if (exportsEl) exportsEl.textContent = j.exportRemaining + ' / ' + j.exportLimit + ' 次';
            if (bindingsEl) bindingsEl.textContent = j.replaceRemaining + ' 次';
            if (daysEl) daysEl.textContent = fmtDate(j.expiresAt);
        }).catch(function () {
            busy = false;
            if (btn) { btn.disabled = false; btn.textContent = '查询授权码'; }
            setMsg('网络异常，请检查后重试', true);
        });
    }

    if (btn) btn.addEventListener('click', query);
    if (input) input.addEventListener('keydown', function (e) { if (e.key === 'Enter') query(); });
}();
