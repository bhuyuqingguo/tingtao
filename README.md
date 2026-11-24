# 观海·听涛（TingTao）

观海听涛，声落成章。

一款本地运行的中文语音整理工具：离线语音转录、批量队列、说话人声纹、规则纪要与多格式导出。转录过程不依赖在线服务，不上传音频、文稿或声纹。

## 功能

- faster-whisper small／medium 模型可选，CPU int8 推理。
- 系统输入音源选择、16 kHz 单声道 WAV 录音，录音可直接离线转录。
- 潮生、远山、听涛、星夜四套随机开场与本地海浪音效；最近 60 秒右对齐滚动历史波形、-12／-6／0 dB 分色电平表、古典标志灯效、窗口红框与任务栏录音提示。
- 录音支持自动防爆音、自动增益和关闭／低／中／高四档流式降噪，录音过程中可调整；转录前可选轻度／标准降噪与响度归一化，默认原声且不修改原文件。
- 二次弹窗与主题统一，窄长文稿阅读区，模型显示名称中文化。
- 本地音频库支持导入、命名、关键词库、搜索、播放、导出与删除。
- 新增加密统一使用观海·八分 v0.3.0 BFQ，音频内容、名称、关键词、会议主题和打点均受保护，口令不明文保存；旧 AES 音频库保留只读兼容，正确解锁后自动迁移。
- 可选择音频并设置独立口令导出 `.bfq` 八分包；口令通过核心标准输入传递，不出现在命令行、配置或日志中。
- 多文件逐个转录，或按队列顺序合并成一份连续文稿。
- 会前填写会议主题、设置最多 30 个专业词提示；可一键带入音频关键词库，仅用于本地模型上下文。
- 会中按重点／决定／待办／疑问打点，支持快捷键与置顶速记小窗；关闭小窗不会停止录音。主题和打点随音频库一并加密，双击可回原音复核。
- 字音校订支持逐句时间戳、点击定位原音、播放跟随、讲话人筛选和逐句编辑；保存时同步写回 TXT、JSON、SRT 与 VTT。
- 转录记录支持名称与正文全文检索，可重新打开历史文稿校订；保守语篇清理只处理明显填充词、重复标点和多余空格。
- WeSpeaker 中文声纹识别与本地持久声纹库，支持讲话人命名和自动匹配。
- 本地规则生成会议纪要并带入会中打点，不要求在线大模型；内容仍需人工复核。
- 记录重命名、依据文稿内容建议文件名。
- 导出 TXT、Markdown、DOCX（Word／WPS 兼容）、SRT、VTT、JSON。
- 山海古典／素简现代主题。
- 内嵌“听涛学堂”12 章详细图文与本地中文语音讲解；每章附原创四步流程图和真实界面截图，点击图片可在软件内放大。支持全文搜索、播放／暂停／停止、进度、音量、倍速及 F1 快捷入口，不调用在线 TTS。
- Windows 与银河麒麟打包脚本；升级在当前软件内一键完成，支持校验、备份与失败回滚，不使用独立升级工具。

当前采用录音或文件完成后离线转录，不包含实时流式字幕、电脑系统内录／混录、云会议、多端同步或在线生成式 AI。速记小窗用于计时与人工打点，不是实时字幕；本地规则纪要不等于大模型长文理解。详细取舍见 `docs/iflyrec-benchmark.md`。

## 平台状态

| 平台 | 当前状态 |
| --- | --- |
| Windows x64 | 已提供完整离线打包和增量升级流程 |
| 银河麒麟 V10 x86_64 | 提供构建脚本；需在目标系统或兼容构建机上验证 |
| macOS | 尚未适配；Windows EXE 不能直接在 Mac 上运行 |

后续 macOS 开发可保留 faster-whisper 后端，并评估 whisper.cpp／Metal 或 MLX Whisper。模型、FFmpeg 和 Python 依赖必须按平台分别准备，不能直接复用 Windows 二进制文件。

## 源码与模型分离

仓库包含源码、测试、Logo、程序生成的短音效、12 章本地教学语音、12 张流程图、12 张真实界面截图和资源清单，不包含约 2 GB 的模型、FFmpeg、部署包、用户配置、转录记录、日志或个人声纹。`scripts/generate_tutorial_audio.py` 可在装有 Microsoft Huihui Desktop 中文语音的 Windows 机器上离线重新生成讲解 WAV；发布软件播放已有 WAV 不需要安装该语音。`scripts/generate_tutorial_visuals.py` 可重新生成原创流程图并截取当前软件页面。

开发机准备模型时需要联网；准备完成后，软件运行和受控环境部署均可离线。模型文件仍受各自原始许可证约束。

## Windows 源码运行

建议使用 Python 3.12 x64：

```powershell
git clone https://github.com/bhuyuqingguo/tingtao.git
cd tingtao
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\download_models.py
```

将 `ffmpeg.exe` 和 `ffprobe.exe` 放入项目根目录的 `ffmpeg` 文件夹，然后运行：

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m offline_transcriber
```

FFmpeg 也可通过包管理器安装后复制到上述目录。发布包使用的 Windows 构建来源见 `assets-manifest.json`。

## 模型

| 模型 | 主文件大小 | 说明 |
| --- | ---: | --- |
| faster-whisper-small | 约 461 MiB | 日常转录，速度优先 |
| faster-whisper-medium | 约 1457 MiB | 更高精度，耗时和内存更高 |
| WeSpeaker CNCeleb ResNet34-LM | 约 25 MiB | 中文声纹嵌入，不是语音识别模型 |

只下载需要的模型：

```powershell
.venv\Scripts\python.exe scripts\download_models.py --model small
.venv\Scripts\python.exe scripts\download_models.py --model medium
.venv\Scripts\python.exe scripts\download_models.py --model speaker
```

下载脚本按已知 SHA-256 校验关键文件。模型发行方更新文件后，校验可能失败，此时应人工审查新版本，不要绕过校验。medium 建议预留约 3–5 GB 峰值内存，实际占用取决于设备和任务参数；large-v3 尚未内置。

## 测试

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m unittest discover -s tests -q
```

## 离线发布包

所有发布包解压后，顶层固定只有两个项目：

1. 一个可执行文件；
2. 一个资源文件夹。

不得把模型、说明或许可证再散放在压缩包顶层。完整包和增量包都遵守此规则。

### 界面内自升级

1.6.1 起，Windows 一键升级会复制当前程序自身及完整 `_internal` 作为私有临时运行环境，在主窗口关闭后替换正式程序、自动启动新版并清理临时文件，不依赖独立升级工具。主题和配置在关闭前保存，临时运行体不进入完整性清单。1.6.2 增加四套随机开场；1.6.3 改为 60 秒历史波形并加入录音音频处理；1.6.4 支持直接读取整个增量 ZIP，无需解压，并在古典风确认页展示发行说明；1.6.5 新增 12 章内嵌教学和本地中文语音讲解；1.6.6 为每章补充流程图、真实截图及原图放大查看；1.6.7 完善离线会议打点、速记小窗、专业词提示、字音校订、全文检索与保守语篇清理；1.6.8 将音频库新加密统一切换为观海·八分 BFQ，支持旧 AES 库验证后自动迁移与独立八分包导出。后续发布仅提供以上一版为基线的增量包。

1.5.0／1.6.0 的旧流程会让运行中的 exe 替换自身，Windows 返回“拒绝访问”并回滚；这类旧代码无法由增量载荷反向修复，必须先使用 1.6.1 过渡完整包，旧增量包不要继续使用。

Windows 构建：

```powershell
.venv\Scripts\python.exe scripts\build_package.py
.venv\Scripts\python.exe scripts\finalize_package.py
```

银河麒麟 V10 x86_64 构建：

```bash
bash scripts/build_kylin.sh
```

麒麟离线构建需先准备 `wheelhouse`，再使用 `OFFLINE_BUILD=1 bash scripts/build_kylin.sh`。目标机架构、系统库和实际运行效果必须单独验收。

## 隐私与使用边界

本地声纹保存在 `data/voiceprints.json`，该目录默认不进入版本控制。声纹相似度只适合辅助文稿整理，不能用于司法身份认定；短句、重叠语音和相似声音可能识别不可靠。自动纪要和自动命名也应结合原文复核。

## 开源许可

项目源码采用 [Apache License 2.0](LICENSE)。第三方组件及模型许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
