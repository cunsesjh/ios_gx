#!/usr/bin/env node
/**
 * 烟雨江湖 · 本地存档工具 —— 本地服务器
 * 用法: node server.js [端口]
 * 默认端口: 8080  (如被占用自动尝试 8081..8085)
 * 访问: http://127.0.0.1:8080
 *
 * 说明:
 *  - 本目录为站点完整镜像（HTML/CSS/JS/图片/加密算法资产/APK）
 *  - /api/runtime-key 为本地内置应答：算法解密密钥固定，会话有效期动态签发
 *  - /api/convert-start 与 /api/open 为本地内置应答：明文 JSON 存档的离线打包与导入授权
 *  - 除授权码查询（license 页对接外部授权服务）外，全部功能离线可用
 */
'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const RUNTIME_KEY = 'BAs/MURRaThpNeBtN7E7xJ5E1BGrWrK4XhmXiXEzf0M=';

// ---- 本地存档打包/导入授权（CXK001 容器） ----
// 原版由外部授权服务下发 fileId/webToken/contentKey；本地部署改为固定值本地应答，
// 使 JSON 存档可在完全离线情况下完成打包与导入。
const CONVERT_FILE_ID = '8f14e45f-ceea-4b3f-9abc-9a8b2c3d4e5f';       // UUID v4 格式
const CONVERT_WEB_TOKEN = 'MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI='; // 32B base64
const CONVERT_CONTENT_KEY = 'MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE='; // 32B base64

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.htm': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.otf': 'font/otf',
  '.eot': 'application/vnd.ms-fontobject',
  '.apk': 'application/vnd.android.package-archive',
  '.enc': 'application/octet-stream',
  '.wasm': 'application/wasm',
  '.txt': 'text/plain; charset=utf-8',
  '.xml': 'application/xml; charset=utf-8',
  '.pdf': 'application/pdf',
  '.mp3': 'audio/mpeg',
  '.mp4': 'video/mp4',
  '.zip': 'application/zip',
};

function send(res, status, headers, body) {
  res.writeHead(status, headers);
  res.end(body);
}

function serveStatic(req, res, pathname) {
  // 防止路径穿越
  let rel = pathname.replace(/\\/g, '/');
  if (rel.startsWith('/')) rel = rel.slice(1);
  if (rel.includes('..')) {
    return send(res, 400, { 'Content-Type': 'text/plain; charset=utf-8' }, 'Bad Request');
  }
  let filePath = path.join(ROOT, rel);
  // 目录请求 -> index.html
  let stat = null;
  try { stat = fs.statSync(filePath); } catch (e) { /* not found */ }
  if (stat && stat.isDirectory()) {
    filePath = path.join(filePath, 'index.html');
    try { stat = fs.statSync(filePath); } catch (e) { stat = null; }
  }
  if (!stat || !stat.isFile()) {
    return send(res, 404, { 'Content-Type': 'text/plain; charset=utf-8' }, '404 Not Found: /' + rel);
  }
  const ext = path.extname(filePath).toLowerCase();
  const type = MIME[ext] || 'application/octet-stream';
  const headers = {
    'Content-Type': type,
    'Content-Length': stat.size,
    'Cache-Control': 'no-cache',
    'X-Content-Type-Options': 'nosniff',
    'Access-Control-Allow-Origin': '*',
  };
  if (ext === '.apk') {
    // 支持下载
    headers['Content-Disposition'] = 'attachment; filename="' + path.basename(filePath) + '"';
  }
  res.writeHead(200, headers);
  fs.createReadStream(filePath).pipe(res);
}

const server = http.createServer((req, res) => {
  let url;
  try {
    url = new URL(req.url, 'http://127.0.0.1');
  } catch (e) {
    return send(res, 400, { 'Content-Type': 'text/plain; charset=utf-8' }, 'Bad Request');
  }
  let pathname;
  try {
    pathname = decodeURIComponent(url.pathname);
  } catch (e) {
    return send(res, 400, { 'Content-Type': 'text/plain; charset=utf-8' }, 'Bad Request');
  }

  if (pathname === '/api/runtime-key') {
    const expires = new Date(Date.now() + 60 * 60 * 1000).toISOString();
    const body = JSON.stringify({ valid: true, key: RUNTIME_KEY, sessionExpiresAt: expires });
    return send(res, 200, {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'Access-Control-Allow-Origin': '*',
      'Content-Length': Buffer.byteLength(body),
    }, body);
  }

  // ---- 本地导入授权接口（POST）----
  if (req.method === 'POST' && pathname === '/api/open') {
    let chunks = [];
    let size = 0;
    req.on('data', (c) => {
      size += c.length;
      if (size > 1024 * 1024) { req.destroy(); return; }
      chunks.push(c);
    });
    req.on('end', () => {
      let payload = {};
      try {
        const raw = Buffer.concat(chunks).toString('utf8');
        if (raw) payload = JSON.parse(raw);
      } catch (e) { /* 忽略 body 解析错误 */ }
      let result;
      {
        // 导入授权：返回 contentKey（原版校验 fileId/webToken 后下发）
        const expires = new Date(Date.now() + 60 * 60 * 1000).toISOString();
        result = { valid: true, contentKey: CONVERT_CONTENT_KEY, expiresAt: expires };
      }
      const body = JSON.stringify(result);
      send(res, 200, {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'no-store',
        'Access-Control-Allow-Origin': '*',
        'Content-Length': Buffer.byteLength(body),
      }, body);
    });
    return;
  }

  serveStatic(req, res, pathname);
});

function listen(port, attempt) {
  server.once('error', (err) => {
    if (err.code === 'EADDRINUSE' && attempt < 5) {
      console.log(`Port ${port} is in use, trying ${port + 1} ...`);
      listen(port + 1, attempt + 1);
    } else {
      console.error('Start failed:', err.message);
      process.exit(1);
    }
  });
  server.listen(port, '127.0.0.1', () => {
    console.log('');
    console.log('  =============================================');
    console.log('   Yanyu Jianghu Local Tool  is running');
    console.log(`   URL: http://127.0.0.1:${port}`);
    console.log('   Close this window to stop the server.');
    console.log('  =============================================');
    console.log('');
    // 自动打开浏览器（Windows 下 start 首个引号参数是窗口标题，必须传空串，否则会把 URL 当标题）
    // YYJH_NO_BROWSER=1 时不开 —— 由 yyjh 工具统一打开带存档的入口页
    if (!process.env.YYJH_NO_BROWSER) {
      const url = `http://127.0.0.1:${port}/`;
      const opener = process.platform === 'win32'
        ? 'cmd /c start ""'
        : process.platform === 'darwin' ? 'open' : 'xdg-open';
      require('child_process').exec(`${opener} "${url}"`);
    }
  });
}

const initialPort = parseInt(process.argv[2], 10) || 8080;
listen(initialPort, 0);
