"""Regression guard for the Pexels-video SSRF allowlist.

`download_pexels_video` takes a URL from a Pexels API response. A crafted
response (or a future code path) must not be able to make the bridge fetch an
arbitrary/internal host. The guard rejects any non-`videos.pexels.com` (https)
URL *before* reaching the network, so the assertion is that `urlopen` is never
called for a disallowed host. Without the guard, `urlopen` would be reached
(and the test would fail), which is what makes this a real regression test
rather than a tautology — a bare `urlopen` to a bogus host also returns False
via a network error.
"""
from unittest.mock import patch

from worker.bridge import image_router


def test_disallowed_host_never_hits_network(tmp_path):
    out = tmp_path / "clip.mp4"
    with patch.object(image_router.urllib_request, "urlopen") as urlopen:
        for bad in (
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata SSRF
            "https://evil.example.com/clip.mp4",          # arbitrary external host
            "http://videos.pexels.com/clip.mp4",          # right host, wrong scheme
            "file:///etc/passwd",                          # non-http scheme
            "not-a-url",
        ):
            assert image_router.download_pexels_video(bad, str(out)) is False
        urlopen.assert_not_called()
    assert not out.exists()


def test_allowed_hosts_reach_network(tmp_path):
    out = tmp_path / "clip.mp4"
    with patch.object(image_router.urllib_request, "urlopen") as urlopen:
        # Stop before any real download, but only reachable once the host passes.
        urlopen.side_effect = OSError("stop before real download")
        for good in (
            "https://videos.pexels.com/video-files/123/clip.mp4",
            "https://player.vimeo.com/external/123.hd.mp4?s=abc",  # Pexels uses Vimeo CDN
        ):
            assert image_router.download_pexels_video(good, str(out)) is False
        assert urlopen.call_count == 2  # both allowlisted hosts reached the fetch
