import logging

from astrbot.core.log import _RecordEnricherFilter


def test_framework_log_can_be_attributed_to_plugin():
    record = logging.LogRecord(
        name="astrbot.core.star",
        level=logging.ERROR,
        pathname="C:/AstrBot/astrbot/core/star/star_manager.py",
        lineno=10,
        msg="plugin failed",
        args=(),
        exc_info=None,
    )
    record.plugin_name = "demo-plugin"

    assert _RecordEnricherFilter().filter(record) is True
    assert record.plugin_tag == "[demo-plugin]"
