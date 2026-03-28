import { Settings } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";
import type { StudioTab } from "../context/StudioContext";

const TAB_LABELS: Record<StudioTab, string> = {
  storyboard: "스토리보드",
  images: "이미지",
  sources: "소싱",
  batch: "배치",
  jobs: "작업",
};

const TABS: StudioTab[] = ["storyboard", "images", "sources", "batch", "jobs"];

export default function TopBar() {
  const { bridgeStatus, activeTab } = useStudioState();
  const actions = useStudioActions();

  return (
    <header className="top-bar">
      <div className="top-bar-brand">
        <span className="top-bar-title">Video Studio</span>
        <span
          className={`bridge-dot bridge-dot-${bridgeStatus}`}
          title={bridgeStatus}
          onClick={actions.recheckBridge}
        />
      </div>

      <div className="mode-toggle">
        {TABS.map((tab) => (
          <button
            key={tab}
            className={`mode-toggle-btn ${activeTab === tab ? "active" : ""}`}
            onClick={() => actions.setActiveTab(tab)}
          >
            {TAB_LABELS[tab]}
          </button>
        ))}
      </div>

      <button className="top-bar-settings" onClick={actions.toggleDebug} title="디버그">
        <Settings size={16} />
      </button>
    </header>
  );
}
