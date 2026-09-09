# YOLO 视频证据分析服务

独立运行的视频分析服务，供主后端 `yolo_server` MCP 调用。

## 功能

- 接收 5 分钟左右的视频文件。
- 按 `frame_interval_seconds` 抽帧，默认每 3 秒 1 帧。
- 使用 Ultralytics YOLO 本地模型识别人员、车辆、货物相关对象。
- 输出关键帧、识别对象、视频摘要、证明目的、风险提示和待确认项。

## 安装

```bash
cd yolo-video-service
pip install -r requirements.txt
```

首次运行会按 `model_path` 自动下载官方模型，例如 `yolo11s.pt`。

## 启动

**必须带环境变量启动**（否则 Qwen-VL 语义摘要会静默降级为规则模板，ASR 音轨转写失败）：

方式一（推荐，Windows）：
```bash
start_service.bat
```

方式二（手动导出环境变量，与 backend/.env 同源）：
```bash
export $(grep -E "^(QWEN_VL_API_URL|QWEN_VL_API_KEY|QWEN_VL_MODEL|ASR_API_URL|ASR_API_KEY|ASR_MAX_CHUNK_SECONDS)=" ../backend/.env | tr -d '\r' | xargs)
python -m uvicorn app:app --host 0.0.0.0 --port 9001
```

健康检查（**degraded 必须为 false**、vl_configured 必须为 true）：
```text
http://127.0.0.1:9001/health
```

## 主后端配置

在 `backend/.env` 中配置：

```env
YOLO_API_URL=http://127.0.0.1:9001/analyze-video
YOLO_MODEL_PATH=yolo11s.pt
YOLO_FRAME_INTERVAL_SECONDS=3
```

## 接口

```text
POST /analyze-video
Content-Type: multipart/form-data
```

字段：

```text
file: 视频文件
frame_interval_seconds: 抽帧间隔，默认 3
model_path: YOLO 模型路径，默认 yolo11s.pt
duration_seconds: 视频时长估计，默认 300
```

返回：

```json
{
  "duration_seconds": 300,
  "frame_interval_seconds": 3,
  "sampled_frames": 100,
  "objects": [],
  "key_frames": [],
  "summary": "视频中出现人员和货车，可能与货物交付、运输或现场作业过程有关。",
  "key_events": [],
  "proof_purpose": "证明现场状态、人员到场、车辆/货物出现、交付或履行过程。",
  "risk_notes": [],
  "need_confirm": [],
  "confidence": 0.82
}
```

## 模型建议

- 轻量：`yolo11n.pt`
- 推荐：`yolo11s.pt`
- 更准但更慢：`yolo11m.pt`

法律证据场景后续可自训模型识别：合同、签收单、货物、托盘、印章、签字区、施工设备等。
