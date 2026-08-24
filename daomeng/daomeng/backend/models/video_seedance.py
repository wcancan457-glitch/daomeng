"""
Seedance 视频生成 API 客户端 (字节跳动 ARK)

"""

import base64
import logging
import os
import sys
import time
from typing import Any, Callable, Optional

import requests

models_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(models_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from config import Config  # noqa: E402

logger = logging.getLogger(__name__)

class SeedanceVideoClient:
    """
    Seedance 视频生成客户端（字节跳动 ARK）
    支持图生视频功能，采用 提交任务 -> 轮询 -> 下载 的异步流程
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 120,
    ) -> None:
        self.api_key = api_key or Config.ARK_API_KEY
        self.base_url = (base_url or Config.ARK_BASE_URL or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        self.timeout = timeout

        if not self.api_key:
            logger.warning("SeedanceVideoClient: ARK_API_KEY 未设置")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _build_submit_payload(
        prompt: str,
        image_base64: str,
        model: str,
        duration: int,
        **kwargs,
    ) -> dict:
        content = []
        if prompt:
            content.append({"type": "text", "text": prompt})
        content.append({
            "type": "image_url",
            "image_url": {"url": image_base64},
            "role": "first_frame",
        })

        payload = {
            "model": model,
            "content": content,
            "duration": duration,
            "ratio": kwargs.get("ratio") or "adaptive",
            "resolution": kwargs.get("resolution") or "720p",
        }
        # ARK 会校验可选字段的类型；None 不是“未设置”，发送 null 会导致参数错误。
        for key in ("seed", "watermark", "generate_audio"):
            value = kwargs.get(key)
            if value is not None:
                payload[key] = value
        return payload

    @staticmethod
    def _provider_error(resp: requests.Response, action: str) -> RuntimeError:
        try:
            data = resp.json()
        except ValueError:
            data = None
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                detail = error.get("message") or error.get("code")
            else:
                detail = data.get("message") or error
        else:
            detail = None
        safe_detail = str(detail or resp.text or "未知错误").strip()[:1000]
        return RuntimeError(f"Seedance {action}失败（HTTP {resp.status_code}）：{safe_detail}")

    def generate_video(
        self,
        prompt: str,
        image_path: str,
        save_path: str,
        model: str = "doubao-seedance-2-0-260128",
        duration: int = 5,
        **kwargs
    ) -> str:
        """
        图生视频完整流程

        Args:
            prompt: 提示词
            image_path: 输入图片本地路径
            save_path: 输出视频保存路径
            model: 模型名称
            duration: 视频时长
        """
        if not self.api_key:
            raise RuntimeError("ARK_API_KEY not set.")

        task_state_callback = kwargs.pop("task_state_callback", None)
        existing_task_id = str(kwargs.pop("provider_task_id", "") or "").strip()
        max_wait_seconds = int(kwargs.pop("max_wait_seconds", 900) or 900)

        # 已经拿到供应商任务 ID 时继续查询，避免页面断线或服务重启后重复计费。
        if existing_task_id:
            task_id = existing_task_id
            self._notify_task_state(task_state_callback, {
                "provider": "ark",
                "provider_task_id": task_id,
                "provider_status": "resuming",
                "model": model,
            })
        else:
            task_id = self._submit_task(prompt, image_path, model, duration, **kwargs)
            self._notify_task_state(task_state_callback, {
                "provider": "ark",
                "provider_task_id": task_id,
                "provider_status": "queued",
                "model": model,
            })
        
        # 2. 轮询等待
        video_url = self._poll_until_done(
            task_id,
            max_wait_seconds=max_wait_seconds,
            task_state_callback=task_state_callback,
        )
        
        # 3. 下载视频
        self._notify_task_state(task_state_callback, {
            "provider": "ark",
            "provider_task_id": task_id,
            "provider_status": "downloading",
            "model": model,
        })
        self._download_video(video_url, save_path)
        self._notify_task_state(task_state_callback, {
            "provider": "ark",
            "provider_task_id": task_id,
            "provider_status": "succeeded",
            "model": model,
        })
        
        return video_url

    @staticmethod
    def _notify_task_state(callback: Optional[Callable[[dict[str, Any]], None]], data: dict[str, Any]) -> None:
        if not callback:
            return
        try:
            callback(data)
        except Exception as exc:
            # 状态回写失败不能中断已经付费的供应商生成任务。
            logger.warning("Seedance task state callback failed: %s", exc)

    def _submit_task(self, prompt: str, image_path: str, model: str, duration: int, **kwargs) -> str:
        # 根据 Seedance 2.0 文档更新接口路径
        url = f"{self.base_url}/contents/generations/tasks"
        
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"输入图片不存在: {image_path}")
            
        with open(image_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(image_path)[1].lower()
        mime = "image/png" if ext == ".png" else "image/jpeg"
        image_base64 = f"data:{mime};base64,{img_data}"

        payload = self._build_submit_payload(prompt, image_base64, model, duration, **kwargs)

        logger.info(f"SeedanceVideoClient: 提交任务 model={model}, duration={duration}s")
        resp = requests.post(
            url,
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
            proxies=Config.requests_proxies("ark"),
        )
        
        if not resp.ok:
            logger.error(f"Seedance 提交失败: {resp.text}")
            raise self._provider_error(resp, "提交任务")
            
        data = resp.json()
        task_id = data.get("id")
        if not task_id:
            raise RuntimeError(f"Seedance API 未返回任务 ID: {data}")
            
        return task_id

    def get_task(self, task_id: str) -> dict[str, Any]:
        url = f"{self.base_url}/contents/generations/tasks/{task_id}"
        resp = requests.get(
            url,
            headers=self._headers(),
            timeout=30,
            proxies=Config.requests_proxies("ark"),
        )
        if not resp.ok:
            raise self._provider_error(resp, "查询任务")
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"Seedance 查询任务返回格式异常: {type(data).__name__}")
        return data

    def _poll_until_done(
        self,
        task_id: str,
        max_polls: Optional[int] = None,
        interval: int = 5,
        max_wait_seconds: int = 900,
        task_state_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> str:
        started_at = time.monotonic()
        deadline = started_at + max(30, max_wait_seconds)
        poll_count = 0
        last_status = ""

        while time.monotonic() < deadline and (max_polls is None or poll_count < max_polls):
            data = self.get_task(task_id)
            poll_count += 1
            status = data.get("status")
            elapsed_seconds = max(0, int(time.monotonic() - started_at))
            if status != last_status:
                logger.info("SeedanceVideoClient: task=%s status=%s elapsed=%ss", task_id, status, elapsed_seconds)
                last_status = str(status or "")
            self._notify_task_state(task_state_callback, {
                "provider": "ark",
                "provider_task_id": task_id,
                "provider_status": status or "unknown",
                "provider_created_at": data.get("created_at"),
                "provider_updated_at": data.get("updated_at"),
                "elapsed_seconds": elapsed_seconds,
                "model": data.get("model"),
            })

            if status == "succeeded":
                # 根据实际返回体，URL 位于 content.video_url 或 video_url
                video_url = data.get("content", {}).get("video_url") or data.get("video_url")
                if not video_url:
                    raise RuntimeError(f"Seedance 任务成功但未返回视频 URL: {data}")
                return video_url
            if status in ("failed", "expired", "cancelled"):
                error_msg = data.get("error", {}).get("message") or data.get("status_msg") or "未知错误"
                raise RuntimeError(f"Seedance 视频生成{status}: {error_msg}")

            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(interval, remaining))

        raise TimeoutError(
            f"Seedance 视频生成等待超时，供应商任务可能仍在执行，可使用任务 ID 恢复：{task_id}"
        )

    def download_task_result(
        self,
        task_id: str,
        save_path: str,
        expected_model: Optional[str] = None,
        expected_duration: Optional[int] = None,
    ) -> dict[str, Any]:
        data = self.get_task(task_id)
        status = data.get("status")
        if status != "succeeded":
            raise RuntimeError(f"Seedance 任务尚未成功，当前状态: {status or 'unknown'}")
        actual_model = str(data.get("model") or "")
        if expected_model and not str(expected_model).startswith("ep-") and actual_model != expected_model:
            raise RuntimeError(
                f"Seedance 任务模型不匹配，任务使用 {actual_model or 'unknown'}，项目需要 {expected_model}"
            )
        actual_duration = data.get("duration")
        if expected_duration is not None and actual_duration is not None:
            if int(actual_duration) != int(expected_duration):
                raise RuntimeError(
                    f"Seedance 任务时长不匹配，任务为 {actual_duration}s，目标片段为 {expected_duration}s"
                )
        video_url = data.get("content", {}).get("video_url") or data.get("video_url")
        if not video_url:
            raise RuntimeError("Seedance 任务成功但未返回视频 URL")
        self._download_video(video_url, save_path)
        return data

    def _download_video(self, url: str, save_path: str):
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        temp_path = f"{save_path}.part"
        resp = requests.get(url, stream=True, timeout=120, proxies=Config.requests_proxies("ark"))
        resp.raise_for_status()
        try:
            with open(temp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            if not os.path.exists(temp_path) or os.path.getsize(temp_path) <= 0:
                raise RuntimeError("Seedance 视频下载完成但文件为空")
            os.replace(temp_path, save_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        logger.info(f"SeedanceVideoClient: 视频已保存: {save_path}")

if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import Config

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # ── 测试参数（按需修改） ──
    # IMAGE_PATH = "code/result/image/test_avail/test_input.png"
    IMAGE_PATH = "code/result/image/test_avail/test_input_human.jpg"
    OUTPUT_PATH = "code/result/video/test_avail/seedance_test_output.mp4"
    PROMPT = "女生把财务报表交给男生，男生看到后喜极而泣"
    # MODELS = ["doubao-seedance-2-0-fast-260128", "doubao-seedance-2-0-260128"]
    MODELS = ["doubao-seedance-2-0-fast-260128"]
    DURATION = 5

    print("=== Seedance (ARK) 图生视频测试 ===")
    api_key = Config.ARK_API_KEY
    base_url = Config.ARK_BASE_URL
    
    if not api_key:
        print("✗ ARK_API_KEY 未设置，请检查 config.yaml 配置")
        sys.exit(1)

    if not os.path.exists(IMAGE_PATH):
        print(f"✗ 输入图片不存在: {IMAGE_PATH}")
        sys.exit(1)

    print(f"  API Key    : {api_key[:6]}***{api_key[-4:]}")
    print(f"  Base URL   : {base_url}")

    for model in MODELS:
        print("\n" + "="*40)
        print(f"  输入图片   : {IMAGE_PATH}")
        print(f"  输出路径   : {OUTPUT_PATH}")
        print(f"  模型       : {model}")
        print(f"  时长       : {DURATION}s")
        if PROMPT:
            print(f"  提示词     : {PROMPT[:80]}")

        try:
            client = SeedanceVideoClient(api_key=api_key, base_url=base_url)
            print("✓ 客户端初始化成功")

            start = time.time()
            video_url = client.generate_video(
                prompt=PROMPT,
                image_path=IMAGE_PATH,
                save_path=OUTPUT_PATH,
                model=model,
                duration=DURATION,
            )
            elapsed = time.time() - start

            print(f"✓ 视频生成完成！耗时 {elapsed:.1f}s")
            print(f"  远端 URL : {video_url}")
            print(f"  本地文件 : {os.path.abspath(OUTPUT_PATH)}")
            print(f"  文件大小 : {os.path.getsize(OUTPUT_PATH) / 1024 / 1024:.2f} MB")
        except Exception as e:
            print(f"✗ 失败: {e}")
            sys.exit(1)
        break  # 只测试第一个模型
