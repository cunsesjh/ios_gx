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

- **统一存档 = `dat.yanyu`**（网页原生格式，YANYUPL1 本地加密容器）：
  har 转存档后自动多产出一份 `output/<ios区-昵称>/<时间戳>/dat.yanyu`；
  `dat.json` 仍保留作明文备份，网页「导入数据」两种都认。
- **自动导入**：向导导入完自动拉起本地网页服务并把存档交给网页的
  last-import 通道（与导出工具 App 同款机制），打开即「已导入」。
- 网页在 `web/`（guanxing4.0 资源整站），本地服务用 Python 直接跑，
  **不需要 Node**：`python run.py serve` / `python run.py serve --stop`。

## 打包 Windows exe

- 云端构建：推送 `v*` 标签到 GitHub，Actions 自动构建并挂到 Release
  （`.github/workflows/build-exe.yml`；首次用去 Settings→Actions→Workflow
  permissions 勾 Read and write）。
- 本地构建：Windows 上双击 `build.bat`，产物在 `dist\yanyu-guanxing.exe`
  （单文件，内含网页整站与 adb，输出/密钥文件生成在 exe 旁边）。
