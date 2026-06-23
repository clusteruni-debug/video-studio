import type { LucideIcon } from "lucide-react";
import { ClipboardCheck, Film, FolderOpen, LayoutDashboard, SearchCheck, Settings, SlidersHorizontal, Sparkles } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";
import type { StudioTab } from "../context/StudioContext";

const TAB_CONFIG: { tab: StudioTab; label: string; icon: LucideIcon }[] = [
  { tab: "home", label: "홈", icon: LayoutDashboard },
  { tab: "topic", label: "소재", icon: SearchCheck },
  { tab: "plan", label: "기획", icon: Film },
  { tab: "sources", label: "소스", icon: FolderOpen },
  { tab: "edit", label: "편집", icon: SlidersHorizontal },
  { tab: "review", label: "검수", icon: ClipboardCheck },
  { tab: "advanced", label: "고급", icon: Sparkles },
];

export default function TopBar() {
  const { bridgeStatus, activeTab } = useStudioState();
  const actions = useStudioActions();

  return (
    <header className="top-bar">
      <div className="top-bar-brand">
        <span className="top-bar-logo">VS</span>
        <span className="top-bar-title">Video Studio</span>
        <span className="top-bar-subtitle">제작 흐름</span>
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
