import { StudioProvider, useStudioState, useStudioActions } from "./context/StudioContext";
import TopBar from "./components/TopBar";
import Sidebar from "./components/Sidebar";
import StoryboardPanel from "./components/StoryboardPanel";
import ProductionHomePanel from "./components/ProductionHomePanel";
import SourcesWorkspacePanel from "./components/SourcesWorkspacePanel";
import EditWorkspacePanel from "./components/EditWorkspacePanel";
import ReviewWorkspacePanel from "./components/ReviewWorkspacePanel";
import AdvancedOpsPanel from "./components/AdvancedOpsPanel";
import GatesPanel from "./components/GatesPanel";
import BottomBar from "./components/BottomBar";
import DebugDrawer from "./components/DebugDrawer";
import SceneDetailPanel from "./components/SceneDetailPanel";
import PaidConfirmDialog from "./components/PaidConfirmDialog";

function StudioShell() {
  const { activeTab, selectedSceneIndex, draftResult, paidConfirmDialog } = useStudioState();
  const actions = useStudioActions();

  const showRightPanel =
    activeTab === "plan" &&
    selectedSceneIndex !== null &&
    draftResult?.scenes?.[selectedSceneIndex] != null;

  return (
    <div className="studio-shell">
      <TopBar />
      <div className="studio-body">
        <Sidebar />
        <main className="main-canvas">
          {activeTab === "home" && <ProductionHomePanel />}
          {activeTab === "topic" && <GatesPanel />}
          {activeTab === "plan" && <StoryboardPanel />}
          {activeTab === "sources" && <SourcesWorkspacePanel />}
          {activeTab === "edit" && <EditWorkspacePanel />}
          {activeTab === "review" && <ReviewWorkspacePanel />}
          {activeTab === "advanced" && <AdvancedOpsPanel />}
        </main>
        {showRightPanel && (
          <aside className="right-panel">
            <SceneDetailPanel />
          </aside>
        )}
      </div>
      <BottomBar />
      <DebugDrawer />
      <PaidConfirmDialog
        open={!!paidConfirmDialog}
        provider={paidConfirmDialog?.provider ?? ""}
        action={paidConfirmDialog?.action ?? ""}
        estimatedCost={paidConfirmDialog?.estimatedCost ?? ""}
        freeAlternative={paidConfirmDialog?.freeAlternative ?? ""}
        onProceed={actions.confirmPaidProceed}
        onUseFree={actions.confirmPaidUseFree}
        onClose={actions.closePaidConfirm}
      />
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
