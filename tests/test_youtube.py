import pytest

from app.youtube import BadVideoLink, format_time, parse_time, parse_youtube_url

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url,expected",
    [
        (f"https://www.youtube.com/watch?v={VID}", (VID, None)),
        (f"https://youtube.com/watch?v={VID}&list=PL123&index=2", (VID, None)),
        (f"https://m.youtube.com/watch?v={VID}&t=90", (VID, 90)),
        (f"https://youtu.be/{VID}?si=abc&t=1m30s", (VID, 90)),
        (f"https://www.youtube.com/shorts/{VID}", (VID, None)),
        (f"https://www.youtube.com/live/{VID}?feature=share", (VID, None)),
        (f"https://www.youtube.com/embed/{VID}?start=45", (VID, 45)),
        (f"www.youtube.com/watch?v={VID}", (VID, None)),
        (f"https://music.youtube.com/watch?v={VID}", (VID, None)),
        (VID, (VID, None)),
    ],
)
def test_parse_youtube_url(url, expected):
    assert parse_youtube_url(url) == expected


@pytest.mark.parametrize(
    "url",
    ["https://vimeo.com/123", "https://www.youtube.com/watch?v=short", "https://www.youtube.com/channel/xyz", "", "hello"],
)
def test_parse_youtube_url_rejects(url):
    with pytest.raises(BadVideoLink):
        parse_youtube_url(url)


@pytest.mark.parametrize(
    "value,seconds",
    [("90", 90), ("1:30", 90), ("01:02:03", 3723), ("1m30s", 90), ("2h", 7200), ("45s", 45), (12, 12), ("", None), (None, None)],
)
def test_parse_time(value, seconds):
    assert parse_time(value) == seconds


def test_parse_time_rejects_garbage():
    with pytest.raises(ValueError):
        parse_time("soon")


def test_format_time():
    assert format_time(5) == "00:05"
    assert format_time(125) == "02:05"
    assert format_time(3725) == "1:02:05"
