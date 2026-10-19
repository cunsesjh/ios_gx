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
