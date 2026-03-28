import type { LucideIcon } from "lucide-react";
import { Settings, Film, ImageIcon, Rss, Layers, Briefcase } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";
import type { StudioTab } from "../context/StudioContext";

const TAB_CONFIG: { tab: StudioTab; label: string; icon: LucideIcon }[] = [
  { tab: "storyboard", label: "스토리보드", icon: Film },
  { tab: "images", label: "이미지", icon: ImageIcon },
  { tab: "sources", label: "소싱", icon: Rss },
  { tab: "batch", label: "배치", icon: Layers },
  { tab: "jobs", label: "작업", icon: Briefcase },
];

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
        {TAB_CONFIG.map(({ tab, label, icon: Icon }) => (
          <button
            key={tab}
            className={`mode-toggle-btn ${activeTab === tab ? "active" : ""}`}
            onClick={() => actions.setActiveTab(tab)}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      <button className="top-bar-settings" onClick={actions.toggleDebug} title="디버그">
        <Settings size={16} />
      </button>
    </header>
  );
}
