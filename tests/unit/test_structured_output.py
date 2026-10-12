import pytest

from astrbot.core.interaction.expression_agent import (
    InteractionExpressionError,
    build_persona_expression_tool_parameters,
    extract_persona_expression_result,
)
from astrbot.core.interaction.structured_output import (
    build_persona_text_example,
    parse_persona_text,
)

_TENDENCY_XML = """
<tendency>
  <Joy>0</Joy><Trust>1</Trust><Fear>2</Fear><Surprise>8</Surprise>
  <Sadness>7</Sadness><Disgust>0</Disgust><Anger>1</Anger><Anticipation>0</Anticipation>
</tendency>
""".strip()


def test_persona_json_example_passes_production_expression_parser():
    schema = build_persona_expression_tool_parameters()
    example = build_persona_text_example(schema, "json")
    result = extract_persona_expression_result(example, output_format="json")
    assert result.speech
    assert result.segments[0].actions == ["nod"]
    assert set(result.segments[0].tendency) == set(
        schema["properties"]["segments"]["items"]["properties"]["tendency"]["required"]
    )
    assert "effect_calls" not in parse_persona_text(example, "json")


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
        </output>
        """,
        "xml",
    )

    assert value["turn_action"] == "reply"
    assert value["segments"][0]["speech"] == "啊……怎么会这样？"
    assert value["segments"][0]["actions"] == ["lower_head"]
    assert value["segments"][0]["tendency"]["Surprise"] == 8


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
""",
        "markdown",
    )

    assert value["turn_action"] == "reply"
    assert value["segments"][0]["speech"] == "啊……怎么会这样？"
    assert value["segments"][0]["actions"] == ["lower_head"]
    assert value["segments"][0]["tendency"]["Surprise"] == 8


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


def test_semantic_xml_parser_rejects_effect_calls_in_expression_output():
    with pytest.raises(ValueError, match="unexpected_fields:effect_calls"):
        parse_persona_text(
            """<output><turn_action>reply</turn_action><segments><segment>
<speech>嗯</speech><actions/><thought/><tendency>
<Joy>0</Joy><Trust>0</Trust><Fear>0</Fear><Surprise>0</Surprise>
<Sadness>0</Sadness><Disgust>0</Disgust><Anger>0</Anger><Anticipation>0</Anticipation>
</tendency></segment></segments><effect_calls><effect_call>
<name>demo.motion</name><arguments><emotion>focused</emotion></arguments><segment_index>0</segment_index>
</effect_call></effect_calls></output>""",
            "xml",
        )
