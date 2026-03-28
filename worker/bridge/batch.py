"""Batch generation — produce N variants of a single topic.

Each variant uses a slightly different prompt phrasing to get diverse outputs.
The batch manager runs variants sequentially in a background thread.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class BatchJob:
    """State for a single batch run."""

    batch_id: str
    topic: str
    template_type: str
    variants: int
    lang: str
    tts_provider: str
    voice_gender: str
    subtitle_style: str = ""
    tone: str = "casual_heyo"
    status: str = "pending"  # pending | running | completed | failed
    progress: int = 0
    results: list[dict] = field(default_factory=list)
    error: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "topic": self.topic,
            "template_type": self.template_type,
            "variants": self.variants,
            "status": self.status,
            "progress": self.progress,
            "total": self.variants,
            "results": self.results,
            "error": self.error,
        }


# Prompt variation suffixes to diversify LLM output across batch variants
_VARIANT_SUFFIXES: dict[str, list[str]] = {
    "ko": [
        "",
        " (다른 관점에서)",
        " (더 짧고 임팩트 있게)",
        " (유머러스하게)",
        " (감성적으로)",
        " (데이터 중심으로)",
        " (스토리텔링으로)",
        " (반전 포함)",
        " (최신 트렌드 반영)",
        " (초보자 눈높이에서)",
    ],
    "en": [
        "",
        " (from a different perspective)",
        " (shorter and more impactful)",
        " (with humor)",
        " (emotionally)",
        " (data-driven)",
        " (as a story)",
        " (with a twist)",
        " (trending now)",
        " (for beginners)",
    ],
}


class BatchManager:
    """Thread-safe batch job manager."""

    MAX_BATCHES = 100

    def __init__(self) -> None:
        self._jobs: dict[str, BatchJob] = {}
        self._lock = threading.Lock()

    def create_batch(
        self,
        topic: str,
        variants: int,
        template_type: str = "news_explainer",
        lang: str = "ko",
        tts_provider: str = "edge",
        voice_gender: str = "female",
        subtitle_style: str = "",
        tone: str = "casual_heyo",
    ) -> str:
        batch_id = f"batch-{uuid.uuid4().hex[:8]}"
        job = BatchJob(
            batch_id=batch_id,
            topic=topic,
            template_type=template_type,
            variants=min(variants, 10),
            lang=lang,
            tts_provider=tts_provider,
            voice_gender=voice_gender,
            subtitle_style=subtitle_style,
            tone=tone,
        )
        with self._lock:
            # Evict oldest completed batches when over capacity
            if len(self._jobs) >= self.MAX_BATCHES:
                done = [
                    (bid, b) for bid, b in self._jobs.items()
                    if b.status in ("completed", "failed")
                ]
                done.sort(key=lambda x: x[1].created_at)
                for bid, _ in done[: max(1, len(done) // 2)]:
                    del self._jobs[bid]
            self._jobs[batch_id] = job
        return batch_id

    def get_status(self, batch_id: str) -> BatchJob | None:
        with self._lock:
            return self._jobs.get(batch_id)

    def list_jobs(self, limit: int = 20) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [j.to_dict() for j in jobs[:limit]]

    def run_batch(self, batch_id: str, generate_fn) -> None:
        """Execute in a background thread.  *generate_fn* receives a dict and
        returns a dict (the same shape as the /api/create-draft response)."""
        job = self._jobs.get(batch_id)
        if not job:
            return
        job.status = "running"

        lang_key = "en" if job.lang.startswith("en") else "ko"
        suffixes = _VARIANT_SUFFIXES.get(lang_key, _VARIANT_SUFFIXES["ko"])

        for i in range(job.variants):
            suffix = suffixes[i % len(suffixes)]
            variant_topic = f"{job.topic}{suffix}"
            try:
                result = generate_fn({
                    "prompt": variant_topic,
                    "lang": job.lang,
                    "tts_provider": job.tts_provider,
                    "voice_gender": job.voice_gender,
                    "template_type": job.template_type,
                    "subtitle_style": job.subtitle_style,
                    "tone": job.tone,
                })
                job.results.append(result)
            except Exception as e:
                job.results.append({"ok": False, "error": str(e), "variant": i + 1})
            job.progress = i + 1

        failed_count = sum(1 for r in job.results if not r.get("ok"))
        job.status = "failed" if failed_count == job.variants else "completed"
