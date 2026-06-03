"""Regression guard for the Pexels-video SSRF allowlist + redirect block.

`download_pexels_video` takes a URL from a Pexels API response. A crafted
response (or a future code path) must not be able to make the bridge fetch an
arbitrary/internal host. The guard rejects any non-`videos.pexels.com` /
`player.vimeo.com` (https) URL *before* reaching the network, so the assertion
is that the opener is never called for a disallowed host. Without the guard the
opener would be reached (and the test would fail), which is what makes this a
real regression test rather than a tautology — a bare fetch to a bogus host
also returns False via a network error.

`_host_is_internal` is the core of the redirect-block (urlopen follows 3xx by
default; an allowlisted CDN could redirect to an internal host).
"""
from unittest.mock import patch

from worker.bridge import image_router


def test_disallowed_host_never_hits_network(tmp_path):
    out = tmp_path / "clip.mp4"
    # Patch the actual network call site (the redirect-blocking opener).
    with patch.object(image_router._PEXELS_OPENER, "open") as opener:
        for bad in (
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata SSRF
            "https://evil.example.com/clip.mp4",          # arbitrary external host
            "http://videos.pexels.com/clip.mp4",          # right host, wrong scheme
            "file:///etc/passwd",                          # non-http scheme
            "not-a-url",
        ):
            assert image_router.download_pexels_video(bad, str(out)) is False
        opener.assert_not_called()
    assert not out.exists()


def test_allowed_hosts_reach_network(tmp_path):
    out = tmp_path / "clip.mp4"
    with patch.object(image_router._PEXELS_OPENER, "open") as opener:
        # Stop before any real download, but only reachable once the host passes.
        opener.side_effect = OSError("stop before real download")
        for good in (
            "https://videos.pexels.com/video-files/123/clip.mp4",
            "https://player.vimeo.com/external/123.hd.mp4?s=abc",  # Pexels uses Vimeo CDN
        ):
            assert image_router.download_pexels_video(good, str(out)) is False
        assert opener.call_count == 2  # both allowlisted hosts reached the fetch


def test_host_is_internal_classification():
    # Redirect guard core: SSRF targets (private/loopback/link-local) are internal,
    # public CDN IPs are not. IP literals resolve without DNS, so this is offline.
    assert image_router._host_is_internal("127.0.0.1") is True
    assert image_router._host_is_internal("169.254.169.254") is True  # cloud metadata
    assert image_router._host_is_internal("10.0.0.5") is True
    assert image_router._host_is_internal("192.168.1.10") is True
    assert image_router._host_is_internal("") is True
    assert image_router._host_is_internal(None) is True
    assert image_router._host_is_internal("8.8.8.8") is False  # public
    assert image_router._host_is_internal("1.1.1.1") is False  # public
