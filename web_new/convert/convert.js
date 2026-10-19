// ============================================================
// 数据转换 (自研版)
// 将烟雨江湖明文 JSON 数据在浏览器本地打包为 CXK001 自研容器,
// 打包完成后可直接导入本观星站解析 (按内容魔数识别, 改名/改后缀均可)。
// 授权: 调自研授权服务 /api/convert-start 换取一次性 contentKey。
// ============================================================
(function () {
    'use strict';

    // ---------- 基础工具 ----------
    function b64ToBytes(s) {
        var bin = atob(String(s || ''));
        var out = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
        return out;
    }
    function bytesToB64(bytes) {
        var bin = '';
        for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
        return btoa(bin);
    }
    function concatBytes(arrs) {
        var total = 0;
        for (var i = 0; i < arrs.length; i++) total += arrs[i].length;
        var out = new Uint8Array(total);
        var off = 0;
        for (var j = 0; j < arrs.length; j++) { out.set(arrs[j], off); off += arrs[j].length; }
        return out;
    }
    function u32be(n) {
        var b = new Uint8Array(4);
        new DataView(b.buffer).setUint32(0, n, false);
        return b;
    }
    function asciiBytes(s) {
        var out = new Uint8Array(s.length);
        for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
        return out;
    }
    function isUuid(s) {
        return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(s || ''));
    }

    // ---------- JSON 数据校验 ----------
    function hasBornTalent(root) {
        var stack = [root];
        while (stack.length) {
            var n = stack.pop();
            if (n && typeof n === 'object') {
                if (Object.prototype.hasOwnProperty.call(n, 'BornTalent')) return true;
                var keys = Object.keys(n);
                for (var i = 0; i < keys.length; i++) {
                    var v = n[keys[i]];
                    if (v && typeof v === 'object') stack.push(v);
                }
            }
        }
        return false;
    }
    function validateSaveJson(text) {
        var obj;
        try {
            obj = JSON.parse(String(text || '').replace(/^\uFEFF/, ''));
        } catch (e) {
            throw new Error('JSON_FORMAT');
        }
        if (!obj || Array.isArray(obj) || typeof obj !== 'object'
            || !obj.MainRole || !obj.globalVariable || !hasBornTalent(obj)) {
            throw new Error('JSON_STRUCTURE');
        }
        return obj;
    }

    // ---------- CXK001 容器打包 (与观星站导入解析严格对应) ----------
    async function buildContainer(jsonText, auth) {
        var webToken = b64ToBytes(auth.webToken);
        var contentKey = b64ToBytes(auth.contentKey);
        if (!isUuid(auth.fileId) || webToken.length !== 32 || contentKey.length !== 32) {
            throw new Error('AUTH_INVALID');
        }
        var nonce = crypto.getRandomValues(new Uint8Array(12));
        var host = (typeof location !== 'undefined' ? String(location.hostname || '') : '').toLowerCase();
        var header = {
            format_version: '1.0',
            file_id: String(auth.fileId).toLowerCase(),
            web_token: bytesToB64(webToken),
            channel: auth.channel,
            created_at: new Date().toISOString(),
            environment: (host === 'localhost' || host === '127.0.0.1' || host.indexOf('-test.') >= 0) ? 'test' : 'product',
            producer: { name: 'cxk-converter', version: '1.0' },
            compression: 'gzip',
            encryption: 'AES-256-GCM',
            nonce: bytesToB64(nonce),
            metadata: {}
        };
        var headerBytes = new TextEncoder().encode(JSON.stringify(header));
        if (headerBytes.length > 16384) throw new Error('AUTH_INVALID');
        var authData = concatBytes([asciiBytes('CXK001'), u32be(headerBytes.length), headerBytes]);
        var compressed = pako.gzip(new TextEncoder().encode(jsonText));
        var key = await crypto.subtle.importKey('raw', contentKey, { name: 'AES-GCM' }, false, ['encrypt']);
        contentKey.fill(0);
        var cipher = new Uint8Array(await crypto.subtle.encrypt(
            { name: 'AES-GCM', iv: nonce, additionalData: authData, tagLength: 128 }, key, compressed));
        return concatBytes([authData, cipher]);
    }

    function buildFileName(fileId, date) {
        var d = date || new Date();
        function p2(x) { return String(x).padStart(2, '0'); }
        var day = d.getFullYear() + p2(d.getMonth() + 1) + p2(d.getDate());
        var time = p2(d.getHours()) + p2(d.getMinutes()) + p2(d.getSeconds());
        return 'yanyu-' + day + '-' + time + '-' + String(fileId).slice(0, 8).toLowerCase() + '-v3.1.yanyu';
    }

    // ---------- 自研授权服务 ----------
    var AUTH_API = '/api/convert-start';
    // ---------- 本地部署模式 (2026-09-24) ----------
    // 原版对接外部授权服务 license.yanyu.cxk-kk.site; 本地部署改为请求本地服务器 /api/convert-start,
    // 由 server.js 本地应答, 无需授权码、无需联网。
    async function relayFetch(path, payload) {
        return await fetch(path, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            cache: 'no-store',
            body: JSON.stringify(payload)
        });
    }

    async function convertStart(payload) {
        var resp;
        try {
            resp = await relayFetch(AUTH_API, payload);
        } catch (e) {
            throw new Error('SERVICE_UNAVAILABLE');
        }
        var data = null;
        try { data = await resp.json(); } catch (e) {}
        if (!resp.ok) {
            if (resp.status === 403 || resp.status === 404) throw new Error('LICENSE_INVALID');
            throw new Error('SERVICE_UNAVAILABLE');
        }
        if (!data || !data.valid || !data.fileId || !data.webToken || !data.contentKey || !data.channel) {
            throw new Error('AUTH_INVALID');
        }
        return data;
    }

    // ---------- 渠道映射 (packageName → 中文渠道名) ----------
    var CHANNELS = {
        'com.lanjing.yanyu.lanjing': '官服',
        'com.lanjing.yanyu.huawei': '华为',
        'com.lanjing.yanyu.mi': '小米',
        'com.lanjing.yanyu.mz': '魅族',
        'com.lanjing.yanyu.aligames': '九游',
        'com.lanjing.yanyu.m4399': '4399',
        'com.lanjing.yanyu.net.nearme.gamecenter': 'OPPO',
        'com.lanjing.yanyu.honor': '荣耀',
        'com.lanjing.yanyu.bilibili': 'Bilibili',
        'com.hetun.uc.yanyu': '抖音',
        'com.wuxia.novastar': '国际服',
        'com.lanjing.yanyu.huluxia': '葫芦侠',
        'com.lanjing.yanyu.ljpre': '先行服',
        'com.lanjing.yanyu.vivo': 'vivo',
        'com.tencent.tmgp.lanjing.yanyu': '应用宝',
        'com.lanjing.yanyu.qihoo': '360',
        'com.lanjing.yanyu.yuedong': '悦动'
    };

    // ---------- UI ----------
    function setMessage(text, kind) {
        var el = document.getElementById('convertMessage');
        if (!el) return;
        el.textContent = text;
        el.classList.toggle('is-error', kind === 'error');
        el.classList.toggle('is-success', kind === 'success');
    }

    var ERR_MSG = {
        JSON_FORMAT: 'JSON 格式不正确，请检查文件内容。',
        JSON_STRUCTURE: '数据不完整（缺少 MainRole / globalVariable / BornTalent）。',
        LICENSE_INVALID: '授权码无效或导出次数已用完。',
        AUTH_INVALID: '授权服务返回的数据不完整，请稍后重试。',
        SERVICE_UNAVAILABLE: '授权服务暂时不可用，请联网后重试。'
    };

    async function doConvert() {
        var fileEl = document.getElementById('convertJsonFile');
        var licenseEl = document.getElementById('convertLicense');
        var channelEl = document.getElementById('convertChannel');
        var btn = document.getElementById('btnConvert');
        var file = fileEl && fileEl.files && fileEl.files[0];
        var code = (licenseEl ? licenseEl.value : '').trim();
        if (!file) return setMessage('请先选择 JSON 数据文件。', 'error');
        // 本地部署模式: 无需授权码, 由本地服务器应答打包授权
        if (code.length < 6) code = 'local-mode';
        btn.disabled = true;
        var auth = null;
        try {
            setMessage('正在校验 JSON 数据…');
            var obj = validateSaveJson(await file.text());
            var jsonText = JSON.stringify(obj);
            var pkg = channelEl ? channelEl.value : 'com.lanjing.yanyu.lanjing';
            var channel = CHANNELS[pkg] || '官服';
            setMessage('正在验证授权码…');
            auth = await convertStart({ code: code, packageName: pkg, channel: channel, appVersion: 'cxk-converter/1.0' });
            setMessage('正在浏览器本地打包…');
            var bytes = await buildContainer(jsonText, auth);
            var fileName = buildFileName(auth.fileId);
            var blob = new Blob([bytes], { type: 'application/octet-stream' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = fileName;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
            licenseEl.value = '';
            setMessage('转换成功，存档已开始下载。', 'success');
            auth = null;
        } catch (e) {
            setMessage(ERR_MSG[e && e.message] || '转换失败，请检查数据后重试。', 'error');
        } finally {
            if (auth) { auth.contentKey = ''; auth.webToken = ''; }
            btn.disabled = false;
        }
    }

    function init() {
        var fileEl = document.getElementById('convertJsonFile');
        if (fileEl) fileEl.addEventListener('change', function () {
            var f = fileEl.files && fileEl.files[0];
            var nameEl = document.getElementById('convertFileName');
            if (nameEl) nameEl.textContent = f ? f.name : '选择 JSON 数据';
            setMessage('本地部署模式：无需授权码，打包后可直接导入观星本地使用。');
        });
        var btn = document.getElementById('btnConvert');
        if (btn) btn.addEventListener('click', doConvert);
    }

    window.validateSaveJson = validateSaveJson;
    window.buildContainer = buildContainer;
    window.buildFileName = buildFileName;
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
