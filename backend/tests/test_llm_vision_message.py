import pytest

from app.ai.llm import LLMMessage, OpenAICompatibleLLMClient


def _client() -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(
        api_key="test-key", base_url="http://127.0.0.1:9/v1", model="qwen-vl-max-latest",
        timeout=5.0, max_retries=0, temperature=0.0, max_output_tokens=256,
        price_input_per_million=0.0, price_output_per_million=0.0, log_calls=False,
    )


def test_text_only_payload_unchanged():
    payload = _client()._build_payload(
        [LLMMessage(role="user", content="你好")], temperature=0.0, max_tokens=8, stream=False
    )
    # 这是既有行为：content 是字符串，不是数组
    assert payload["messages"] == [{"role": "user", "content": "你好"}]


def test_single_image_becomes_content_parts():
    payload = _client()._build_payload(
        [LLMMessage(role="user", content="识图", images=("data:image/png;base64,AAA",))],
        temperature=0.0, max_tokens=8, stream=False,
    )
    content = payload["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "识图"}
    assert content[1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}


def test_multiple_images_are_appended_in_order():
    payload = _client()._build_payload(
        [LLMMessage(role="user", content="看图", images=("data:image/png;base64,1", "data:image/png;base64,2"))],
        temperature=0.0, max_tokens=8, stream=False,
    )
    urls = [part["image_url"]["url"] for part in payload["messages"][0]["content"][1:]]
    assert urls == ["data:image/png;base64,1", "data:image/png;base64,2"]


def test_system_message_with_images_is_rejected():
    with pytest.raises(ValueError):
        LLMMessage(role="system", content="规则", images=("data:image/png;base64,AAA",))