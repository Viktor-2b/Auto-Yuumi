# 🐱 全自动辅助系统 (Yuumi Auto Script)

基于 Python 的高级视觉自动化。
集成了屏幕实时监测、自动加点以及基于坐标的键鼠模拟。

---

## ⚠️ 核心前置要求

### 1. 必须以【管理员身份】运行
* **开发时：** 请右键点击 PyCharm（或 VSCode）图标 -> `以管理员身份运行`。
* **部署时：** 若通过终端运行，请使用管理员权限打开 CMD 或 PowerShell。
### 2. 安装 Tesseract-OCR 引擎
1. 前往 [Tesseract 官方/开源镜像站](https://github.com/UB-Mannheim/tesseract/wiki) 下载 Windows 安装包（64位）。
2. 安装到默认路径：`C:\Program Files\Tesseract-OCR\`。
3. 如果修改了安装路径，请同步修改主代码中的 `tesseract_cmd` 变量。
### 3. 游戏内视频与 UI 设置
脚本内部使用了写死的相对/绝对像素坐标（血条、技能图标、商店等），请确保游戏内设置一致：
* **分辨率：** 应设置为 `1078 x 1080`。
* **窗口模式：** 必须设置为 **窗口化 (Windowed)**。
* **界面缩放：** 。

## 📦 环境配置与安装

1. **克隆/下载本项目**到一个纯净的文件夹。
2. **创建虚拟环境** 。
3. **安装依赖库：**
   在终端中运行以下命令安装必备的第三方库：
   ```bash
   pip install -r requirements.txt