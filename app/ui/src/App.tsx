import { StudioProvider, useStudioState } from "./context/StudioContext";
import TopBar from "./components/TopBar";
import Sidebar from "./components/Sidebar";
import StoryboardPanel from "./components/StoryboardPanel";
import ImageCanvas from "./components/ImageCanvas";
import SourcesPanel from "./components/SourcesPanel";
import BatchPanel from "./components/BatchPanel";
import JobsPanel from "./components/JobsPanel";
import BottomBar from "./components/BottomBar";
import DebugDrawer from "./components/DebugDrawer";
import SceneDetailPanel from "./components/SceneDetailPanel";

function StudioShell() {
  const { activeTab, selectedSceneIndex, draftResult } = useStudioState();

  const showRightPanel =
    activeTab === "storyboard" &&
    selectedSceneIndex !== null &&
    draftResult?.scenes?.[selectedSceneIndex] != null;

  return (
    <div className="studio-shell">
      <TopBar />
      <div className="studio-body">
        <Sidebar />
        <main className="main-canvas">
          {activeTab === "storyboard" && <StoryboardPanel />}
          {activeTab === "images" && <ImageCanvas />}
          {activeTab === "sources" && <SourcesPanel />}
          {activeTab === "batch" && <BatchPanel />}
          {activeTab === "jobs" && <JobsPanel />}
        </main>
        {showRightPanel && (
          <aside className="right-panel">
            <SceneDetailPanel />
          </aside>
        )}
      </div>
      <BottomBar />
      <DebugDrawer />
    </div>
  );
}

export default function App() {
  return (
    <StudioProvider>
      <StudioShell />
    </StudioProvider>
  );
}
