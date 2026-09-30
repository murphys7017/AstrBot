import asyncio
import base64
import json
import os
import uuid

import aiohttp

from astrbot import logger
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path
from astrbot.core.utils.datetime_utils import generate_timestamp_id

from ..entities import ProviderType
from ..provider import TTSProvider
from ..register import register_provider_adapter


@register_provider_adapter(
    "volcengine_tts",
    "火山引擎 TTS",
    provider_type=ProviderType.TEXT_TO_SPEECH,
)
class ProviderVolcengineTTS(TTSProvider):
    def __init__(self, provider_config: dict, provider_settings: dict) -> None:
        super().__init__(provider_config, provider_settings)
        self.api_key = provider_config.get("api_key", "")
        self.appid = provider_config.get("appid", "")
        self.cluster = provider_config.get("volcengine_cluster", "")
        self.voice_type = provider_config.get("volcengine_voice_type", "")
        self.speed_ratio = provider_config.get("volcengine_speed_ratio", 1.0)
        self.api_base = provider_config.get(
            "api_base",
            "https://openspeech.bytedance.com/api/v1/tts",
        )
        self.timeout = provider_config.get("timeout", 20)

    def _build_request_payload(self, text: str) -> dict:
        return {
            "app": {
                "appid": self.appid,
                "token": self.api_key,
                "cluster": self.cluster,
            },
            "user": {"uid": str(uuid.uuid4())},
            "audio": {
                "voice_type": self.voice_type,
                "encoding": "mp3",
                "speed_ratio": self.speed_ratio,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0,
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "text_type": "plain",
                "operation": "query",
                "with_frontend": 1,
                "frontend_type": "unitTson",
            },
        }

    async def get_audio(self, text: str) -> str:
        """异步方法获取语音文件路径"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer; {self.api_key}",
        }

        payload = self._build_request_payload(text)

        logger.debug(
            "Volcengine TTS request prepared: endpoint=%s payload_keys=%s text_length=%s",
            self.api_base,
            sorted(payload),
            len(text),
        )

        try:
            async with (
                aiohttp.ClientSession(headers=self.request_headers) as session,
                session.post(
                    self.api_base,
                    data=json.dumps(payload),
                    headers=headers,
                    timeout=self.timeout,
                ) as response,
            ):
                logger.debug("Volcengine TTS response status: status=%s", response.status)

                response_text = await response.text()
                logger.debug(
                    "Volcengine TTS response received: body_length=%s",
                    len(response_text),
                )

                if response.status == 200:
                    resp_data = json.loads(response_text)

                    if "data" in resp_data:
                        audio_data = base64.b64decode(resp_data["data"])

                        temp_dir = get_astrbot_temp_path()
                        os.makedirs(temp_dir, exist_ok=True)
                        file_path = os.path.join(
                            temp_dir,
                            f"volcengine_tts_{generate_timestamp_id()}.mp3",
                        )

                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(
                            None,
                            lambda: open(file_path, "wb").write(audio_data),
                        )

                        return file_path
                    raise Exception(
                        "火山引擎 TTS API 返回错误: response_keys="
                        f"{sorted(resp_data)}"
                    )
                raise Exception(
                    "火山引擎 TTS API 请求失败: "
                    f"status={response.status}, response_length={len(response_text)}",
                )

        except Exception as e:
            logger.debug(
                "Volcengine TTS request failed: error_type=%s",
                type(e).__name__,
                exc_info=True,
            )
            raise Exception(f"火山引擎 TTS 异常: {type(e).__name__}") from e
