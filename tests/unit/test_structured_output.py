import pytest

from astrbot.core.interaction.effects import PersonaEffectSpec
from astrbot.core.interaction.expression_agent import (
    InteractionExpressionError,
    build_persona_expression_tool_parameters,
    extract_persona_expression_result,
)
from astrbot.core.interaction.structured_output import parse_persona_text

_TENDENCY_XML = """
<tendency>
  <Joy>0</Joy><Trust>1</Trust><Fear>2</Fear><Surprise>8</Surprise>
  <Sadness>7</Sadness><Disgust>0</Disgust><Anger>1</Anger><Anticipation>0</Anticipation>
</tendency>
""".strip()


def test_parse_semantic_xml_persona_output():
    value = parse_persona_text(
        f"""
        <output>
          <turn_action>reply</turn_action>
          <segments>
            <segment>
              <speech>啊……怎么会这样？</speech>
              <actions><action>lower_head</action></actions>
              <thought>这件事出乎意料</thought>
              {_TENDENCY_XML}
            </segment>
          </segments>
          <effect_calls />
        </output>
        """,
        "xml",
    )

    assert value["turn_action"] == "reply"
    assert value["segments"][0]["speech"] == "啊……怎么会这样？"
    assert value["segments"][0]["actions"] == ["lower_head"]
    assert value["segments"][0]["tendency"]["Surprise"] == 8
    assert value["effect_calls"] == []


def test_parse_semantic_markdown_persona_output():
    value = parse_persona_text(
        """# output
## turn_action
> reply
## segments
### segment
#### speech
> 啊……怎么会这样？
#### actions
##### action
> lower_head
#### thought
> 这件事出乎意料
#### tendency
##### Joy
0
##### Trust
1
##### Fear
2
##### Surprise
8
##### Sadness
7
##### Disgust
0
##### Anger
1
##### Anticipation
0
## effect_calls
""",
        "markdown",
    )

    assert value["turn_action"] == "reply"
    assert value["segments"][0]["speech"] == "啊……怎么会这样？"
    assert value["segments"][0]["actions"] == ["lower_head"]
    assert value["segments"][0]["tendency"]["Surprise"] == 8
    assert value["effect_calls"] == []


@pytest.mark.parametrize("output_format", ["xml", "markdown"])
def test_semantic_text_parser_rejects_embedded_json(output_format):
    text = (
        '<output>{"turn_action":"reply"}</output>'
        if output_format == "xml"
        else '# output\n> {"turn_action":"reply"}'
    )
    with pytest.raises(ValueError):
        parse_persona_text(text, output_format)


def test_production_extractor_reports_text_format_errors_as_expression_errors():
    with pytest.raises(InteractionExpressionError) as exc_info:
        extract_persona_expression_result("# output\n> free text", output_format="markdown")

    assert exc_info.value.reason == "invalid_persona_expression_format"


def test_semantic_xml_parser_uses_dynamic_effect_schema():
    effect = PersonaEffectSpec(
        plugin_id="test",
        name="demo.motion",
        description="demo",
        parameters={
            "type": "object",
            "properties": {"emotion": {"type": "string"}},
            "required": ["emotion"],
            "additionalProperties": False,
        },
        metadata={"required_per_segment": True},
    )
    payload = parse_persona_text(
        """<output><turn_action>reply</turn_action><segments><segment>
<speech>嗯</speech><actions/><thought/><tendency>
<Joy>0</Joy><Trust>0</Trust><Fear>0</Fear><Surprise>0</Surprise>
<Sadness>0</Sadness><Disgust>0</Disgust><Anger>0</Anger><Anticipation>0</Anticipation>
</tendency></segment></segments><effect_calls><effect_call>
<name>demo.motion</name><arguments><emotion>focused</emotion></arguments><segment_index>0</segment_index>
</effect_call></effect_calls></output>""",
        "xml",
        schema=build_persona_expression_tool_parameters([effect]),
    )

    assert payload["effect_calls"][0]["arguments"] == {"emotion": "focused"}
    assert payload["effect_calls"][0]["segment_index"] == 0
