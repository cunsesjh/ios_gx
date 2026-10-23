# 简易使用说明

观星工具，仅限版本（2026-10-03）

## 安装python

[python.org](https://www.python.org) 官网选择任一大于等于的3.8版本。

开发版本为3.11.11，可选 [https://www.python.org/downloads/release/python-3119](https://www.python.org/downloads/release/python-3119/)。

安装时记得勾选 "Add Python to PATH"，方便直接在命令行调用。

## 安装依赖

可选安装依赖，优化视图和爆破速度。
如果第三方库下载较慢，请自行查询如何修改channels使用镜像下载，或者直接跳过此步。

win + R —— cmd —— 回车，打开命令行

```bash
# 假设你的项目文件夹在D:/ios_gx
cd /d D:/ios_gx
pip install -r requirements.txt
```

## 使用方法

### 直接用 exe（推荐，不用装 Python）

到 GitHub Releases 页下载最新的 `ios观星.exe`，双击即用：

- 无需安装 Python，单文件自带全部运行环境和网页版
- 生成的存档/密钥文件统一在 `%LOCALAPPDATA%\yanyu-guanxing\`，不污染桌面
- 首次运行若弹出蓝色的“已保护你的电脑”（SmartScreen），点“更多信息 → 仍要运行”即可（exe 未买代码签名证书，正常现象）
- 建议放到普通文件夹（如 `D:\ios观星\`）再双击

### 快速启动

```bash
cd /d D:/ios_gx
python run.py
```

后续按照指引进行操作即可

### iOS抓包

- 安装免费开源抓包工具 ProxyPin ，iOS直接去应用商店即可

抓包流程

1. 进入游戏，回到主界面，在主界面退出登录
2. 打开proxyin，开启抓包（无需开启HTTPS代理）
3. 打开游戏，登录（qq/微信/邮箱），进入区服，上传一次存档
4. 回到proxypin，停止抓包
5. proxypin右上角三点 —— 视图导出 —— （新版本要选择HAR格式）
6. 将导出的结果传输到电脑，然后启动程序`python run.py`进行解析

## 存档与网页（guanxing4.0 整合版）

- **存档 = `dat.json`**（明文）：har 转存档后只出一份
  `output/<ios区-昵称>/<时间戳>/dat.json`，网页「导入数据」直接认。
- **自动导入 + 自动开首页**：向导导入完自动拉起本地网页服务，把 dat.json 交给网页的
  last-import 通道（与导出工具 App 同款机制），浏览器打开的是**首页 index.html**，
  进去就是「已导入」状态。
- 网页在 `web/`（guanxing4.0 资源整站），本地服务用 Python 直接跑，
  **不需要 Node**：`python run.py serve` / `python run.py serve --stop`。
  向导拉起的后台服务**空闲 30 分钟会自动退出**（不占端口/内存），
  下次跑向导自动再拉起。

## 打包 Windows exe

- 云端构建：推送 `v*` 标签到 GitHub，Actions 自动构建并挂到 Release
  （`.github/workflows/build-exe.yml`；首次用去 Settings→Actions→Workflow
  permissions 勾 Read and write）。
- 本地构建：Windows 上双击 `build.bat`，产物在 `dist\ios观星.exe`
  （单文件，内含网页整站与 adb；输出/密钥文件生成在 `%LOCALAPPDATA%\yanyu-guanxing\`）。
