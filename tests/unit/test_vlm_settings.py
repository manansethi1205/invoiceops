import pytest
from pydantic import ValidationError

from invoiceops.config import Settings


def test_vlm_is_disabled_and_model_less_by_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.vlm_enabled is False
    assert settings.vlm_model == ""


def test_enabled_openai_requires_model_and_credentials_without_secret_leakage() -> None:
    with pytest.raises(ValidationError, match="VLM_MODEL"):
        Settings(_env_file=None, vlm_enabled=True)
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, vlm_enabled=True, vlm_model="vision-model")
    assert "OpenAI credentials" in str(error.value)
    assert "api_key" not in str(error.value).casefold()


def test_fake_provider_needs_model_but_not_credentials() -> None:
    settings = Settings(
        _env_file=None,
        vlm_enabled=True,
        vlm_provider="fake",
        vlm_model="fake-vision",
    )
    assert settings.openai_api_key is None
