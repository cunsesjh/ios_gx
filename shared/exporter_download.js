// 下载链接最终覆写: 固定指向当前发布文件名 (防 save_decrypt.js 动态拼接历史文件名)
(function () {
    function syncExporterDownload() {
        var link = document.getElementById('saveExporterDownload');
        if (link) link.href = 'downloads/yanyu-cxk-v2.9.0.apk';
    }
    syncExporterDownload();
    document.addEventListener('DOMContentLoaded', syncExporterDownload);
    var selector = document.getElementById('saveFormatVersion');
    if (selector) selector.addEventListener('change', syncExporterDownload);
    window.addEventListener('load', syncExporterDownload);
})();
