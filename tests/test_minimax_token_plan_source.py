from astrbot.core.provider.sources.minimax_token_plan_source import (
    ProviderMiniMaxTokenPlan,
)


def test_minimax_token_plan_supports_prompt_only_formats_without_native_json_claim():
    provider = ProviderMiniMaxTokenPlan.__new__(ProviderMiniMaxTokenPlan)
    provider.provider_config = {"type": "minimax_token_plan"}

    for output_format in ("json", "xml", "markdown"):
        assert provider.supports_output_format_test_mode(
            output_format, "prompt_only"
        )

    assert not provider.supports_output_format_test_mode(
        "json", "provider_native_json"
    )
    assert not provider.supports_output_format_test_mode(
        "json", "provider_native_json_schema"
    )


def test_minimax_token_plan_rejects_native_modes_for_non_json_formats():
    provider = ProviderMiniMaxTokenPlan.__new__(ProviderMiniMaxTokenPlan)
    provider.provider_config = {"type": "minimax_token_plan"}

    for output_format in ("xml", "markdown"):
        assert not provider.supports_output_format_test_mode(
            output_format, "provider_native_json"
        )
        assert not provider.supports_output_format_test_mode(
            output_format, "provider_native_json_schema"
        )


def test_minimax_token_plan_keeps_tool_call_boundary_separate_from_format_tests():
    provider = ProviderMiniMaxTokenPlan.__new__(ProviderMiniMaxTokenPlan)
    provider.provider_config = {"type": "minimax_token_plan"}
    provider.model_name = "MiniMax-M2.7"

    assert provider.supports_output_contract_strategy("prompt_only")
    assert provider.supports_output_contract_strategy("protocol_tool_call")
    assert not provider.supports_output_contract_strategy("protocol_native_json")

    provider.set_model("MiniMax-M3.1-Flash-Preview")
    assert provider.supports_output_contract_strategy("prompt_only")
    assert not provider.supports_output_contract_strategy("protocol_tool_call")
    assert not provider.supports_output_format_test_mode(
        "json", "provider_native_json"
    )
