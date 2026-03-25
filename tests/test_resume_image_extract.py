from io import BytesIO


def test_extract_resume_text_uses_llm_vision_for_images(monkeypatch):
    from PIL import Image

    import backend.md_quiz.services.resume_service as resume_service

    calls = {}

    def fake_call_llm_vision_text(*, image_url: str, prompt: str, system: str | None = None, model: str | None = None):
        calls["image_url"] = image_url
        calls["prompt"] = prompt
        calls["system"] = system
        return "张 三\n13800138000\nPython 开发"

    monkeypatch.setattr(resume_service, "call_llm_vision_text", fake_call_llm_vision_text)

    img = Image.new("RGB", (32, 16), color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")

    text = resume_service.extract_resume_text(buf.getvalue(), "resume.png")

    assert text == "张三\n13800138000\nPython 开发"
    assert calls["image_url"].startswith("data:image/png;base64,")
    assert "简历图片" in calls["prompt"]
