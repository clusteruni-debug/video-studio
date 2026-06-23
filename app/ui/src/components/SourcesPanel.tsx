import { useState } from "react";
import { Rss, Newspaper, Loader, ExternalLink } from "lucide-react";
import { fetchRedditPosts, autoRedditDraft, fetchNewsHeadlines, autoNewsDraft } from "../lib/bridge";
import type { RedditPost, NewsArticle, DraftResult } from "../lib/bridge";
import { useStudioState, useStudioActions } from "../context/StudioContext";

type SourceTab = "reddit" | "news";

export default function SourcesPanel() {
  const { lang, ttsProvider, voiceGender, tone, subtitleStyle } = useStudioState();
  const actions = useStudioActions();
  const [sourceTab, setSourceTab] = useState<SourceTab>("reddit");

  // Reddit state
  const [subreddit, setSubreddit] = useState("todayilearned");
  const [redditSort, setRedditSort] = useState("hot");
  const [posts, setPosts] = useState<RedditPost[]>([]);
  const [loadingReddit, setLoadingReddit] = useState(false);
  const [generatingPostIdx, setGeneratingPostIdx] = useState<number | null>(null);

  // News state
  const [newsQuery, setNewsQuery] = useState("");
  const [newsCountry, setNewsCountry] = useState("kr");
  const [newsCategory, setNewsCategory] = useState("general");
  const [articles, setArticles] = useState<NewsArticle[]>([]);
  const [loadingNews, setLoadingNews] = useState(false);
  const [generatingArticleIdx, setGeneratingArticleIdx] = useState<number | null>(null);

  const [lastResult, setLastResult] = useState<DraftResult | null>(null);

  // Reddit handlers
  const handleFetchReddit = async () => {
    setLoadingReddit(true);
    setPosts([]);
    try {
      const res = await fetchRedditPosts(subreddit, redditSort, 15);
      if (res.ok && res.posts) setPosts(res.posts);
    } finally {
      setLoadingReddit(false);
    }
  };

  const handleAutoReddit = async (post: RedditPost, idx: number) => {
    setGeneratingPostIdx(idx);
    setLastResult(null);
    try {
      const res = await autoRedditDraft({
        subreddit: post.subreddit, lang, tts_provider: ttsProvider,
        voice_gender: voiceGender, tone, subtitle_style: subtitleStyle,
      });
      if (res.ok) setLastResult(res);
    } finally {
      setGeneratingPostIdx(null);
    }
  };

  // News handlers
  const handleFetchNews = async () => {
    setLoadingNews(true);
    setArticles([]);
    try {
      const res = await fetchNewsHeadlines(newsQuery || undefined, newsCountry, newsCategory);
      if (res.ok && res.articles) setArticles(res.articles);
    } finally {
      setLoadingNews(false);
    }
  };

  const handleAutoNews = async (article: NewsArticle, idx: number) => {
    setGeneratingArticleIdx(idx);
    setLastResult(null);
    try {
      const res = await autoNewsDraft({
        q: article.title, country: newsCountry, category: newsCategory,
        lang, tts_provider: ttsProvider, voice_gender: voiceGender, tone, subtitle_style: subtitleStyle,
      });
      if (res.ok) setLastResult(res);
    } finally {
      setGeneratingArticleIdx(null);
    }
  };

  // View result in planning — dispatch draft result then switch tab
  const viewInStoryboard = () => {
    if (lastResult) {
      actions.setDraftResult(lastResult);
      actions.setActiveTab("plan");
    }
  };

  return (
    <div>
      {/* Sub-tab toggle */}
      <div className="mode-toggle batch-mode-toggle" style={{ maxWidth: 240, marginBottom: 16 }}>
        <button
          className={`mode-toggle-btn ${sourceTab === "reddit" ? "active" : ""}`}
          onClick={() => setSourceTab("reddit")}
        >
          <Rss size={12} style={{ marginRight: 4 }} /> Reddit
        </button>
        <button
          className={`mode-toggle-btn ${sourceTab === "news" ? "active" : ""}`}
          onClick={() => setSourceTab("news")}
        >
          <Newspaper size={12} style={{ marginRight: 4 }} /> News
        </button>
      </div>

      {/* Reddit panel */}
      {sourceTab === "reddit" && (
        <div>
          <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
            <div className="sidebar-field compact" style={{ flex: 1, minWidth: 120 }}>
              <span>서브레딧</span>
              <input value={subreddit} onChange={(e) => setSubreddit(e.target.value)} placeholder="todayilearned" />
            </div>
            <div className="sidebar-field compact" style={{ width: 100 }}>
              <span>정렬</span>
              <select value={redditSort} onChange={(e) => setRedditSort(e.target.value)}>
                <option value="hot">Hot</option>
                <option value="top">Top</option>
                <option value="new">New</option>
              </select>
            </div>
            <div style={{ display: "flex", alignItems: "flex-end" }}>
              <button className="chip" onClick={handleFetchReddit} disabled={loadingReddit}>
                {loadingReddit ? <Loader size={12} style={{ animation: "spin 1s linear infinite" }} /> : "불러오기"}
              </button>
            </div>
          </div>

          {/* Posts list */}
          {posts.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {posts.map((post, i) => (
                <div key={i} className="scene-detail-asset-row" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: "0.85rem", fontWeight: 500 }}>{post.title}</div>
                    <div style={{ fontSize: "0.72rem", color: "var(--text-tertiary)" }}>
                      r/{post.subreddit} · {post.score.toLocaleString()} pts
                    </div>
                  </div>
                  <a href={post.url.startsWith("http") ? post.url : "#"} target="_blank" rel="noreferrer" className="subtle-button" style={{ textDecoration: "none" }}>
                    <ExternalLink size={12} />
                  </a>
                  <button
                    className="chip"
                    disabled={generatingPostIdx !== null}
                    onClick={() => handleAutoReddit(post, i)}
                  >
                    {generatingPostIdx === i ? <Loader size={12} style={{ animation: "spin 1s linear infinite" }} /> : "자동 생성"}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* News panel */}
      {sourceTab === "news" && (
        <div>
          <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
            <div className="sidebar-field compact" style={{ flex: 1, minWidth: 140 }}>
              <span>검색어</span>
              <input value={newsQuery} onChange={(e) => setNewsQuery(e.target.value)} placeholder="검색어 (선택)" />
            </div>
            <div className="sidebar-field compact" style={{ width: 80 }}>
              <span>국가</span>
              <select value={newsCountry} onChange={(e) => setNewsCountry(e.target.value)}>
                <option value="kr">KR</option>
                <option value="us">US</option>
                <option value="jp">JP</option>
              </select>
            </div>
            <div className="sidebar-field compact" style={{ width: 100 }}>
              <span>카테고리</span>
              <select value={newsCategory} onChange={(e) => setNewsCategory(e.target.value)}>
                <option value="general">일반</option>
                <option value="technology">기술</option>
                <option value="business">비즈니스</option>
                <option value="science">과학</option>
                <option value="entertainment">엔터</option>
                <option value="sports">스포츠</option>
                <option value="health">건강</option>
              </select>
            </div>
            <div style={{ display: "flex", alignItems: "flex-end" }}>
              <button className="chip" onClick={handleFetchNews} disabled={loadingNews}>
                {loadingNews ? <Loader size={12} style={{ animation: "spin 1s linear infinite" }} /> : "검색"}
              </button>
            </div>
          </div>

          {/* Articles list */}
          {articles.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {articles.map((article, i) => (
                <div key={i} className="scene-detail-asset-row" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: "0.85rem", fontWeight: 500 }}>{article.title}</div>
                    <div style={{ fontSize: "0.72rem", color: "var(--text-tertiary)" }}>{article.source}</div>
                  </div>
                  <a href={article.url.startsWith("http") ? article.url : "#"} target="_blank" rel="noreferrer" className="subtle-button" style={{ textDecoration: "none" }}>
                    <ExternalLink size={12} />
                  </a>
                  <button
                    className="chip"
                    disabled={generatingArticleIdx !== null}
                    onClick={() => handleAutoNews(article, i)}
                  >
                    {generatingArticleIdx === i ? <Loader size={12} style={{ animation: "spin 1s linear infinite" }} /> : "자동 생성"}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Last result */}
      {lastResult?.ok && (
        <div style={{
          marginTop: 16, padding: 12, background: "var(--success-dim)",
          border: "1px solid rgba(52,199,123,0.2)", borderRadius: "var(--radius-sm)",
        }}>
          <div style={{ fontSize: "0.88rem", fontWeight: 600, color: "var(--success)", marginBottom: 4 }}>
            초안 생성 완료
          </div>
          <div style={{ fontSize: "0.78rem", color: "var(--text-secondary)" }}>
            {lastResult.scenes?.length}씬 / {lastResult.total_duration?.toFixed(1)}s
          </div>
          <button className="chip" onClick={viewInStoryboard} style={{ marginTop: 8 }}>
            스토리보드에서 보기
          </button>
        </div>
      )}
    </div>
  );
}
