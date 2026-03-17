import type { BudgetMode } from "../../../../shared/contracts/plan";
import type { BridgeHealth } from "../lib/bridge";
import type { ProviderAvailability, StudioProjectRecord } from "../lib/planner";
import { samplePrompts } from "../lib/sample-data";
import {
    bridgeSummary,
    formatUsd,
    plannerLabel,
    type BridgeStatus,
} from "./shared";

export interface ComposerPanelProps {
    prompt: string;
    onPromptChange: (value: string) => void;
    budgetMode: BudgetMode;
    onBudgetModeChange: (mode: BudgetMode) => void;
    monthlyCapUsd: number;
    onMonthlyCapUsdChange: (value: number) => void;
    availability: ProviderAvailability;
    onAvailabilityChange: (updater: (current: ProviderAvailability) => ProviderAvailability) => void;
    preferBridge: boolean;
    onPreferBridgeChange: (value: boolean) => void;
    bridgeStatus: BridgeStatus;
    bridgeHealth: BridgeHealth | null;
    bridgeMessage: string;
    premiumSceneCount: number;
    selectedProjectAssetCount: number;
    selectedProject: StudioProjectRecord | null;
    isGenerating: boolean;
    onRefreshBridge: () => void;
    onGenerate: () => void;
}

export default function ComposerPanel(props: ComposerPanelProps) {
    const {
        prompt,
        onPromptChange,
        budgetMode,
        onBudgetModeChange,
        monthlyCapUsd,
        onMonthlyCapUsdChange,
        availability,
        onAvailabilityChange,
        preferBridge,
        onPreferBridgeChange,
        bridgeStatus,
        bridgeHealth,
        bridgeMessage,
        premiumSceneCount,
        selectedProjectAssetCount,
        selectedProject,
        isGenerating,
        onRefreshBridge,
        onGenerate,
    } = props;

    return (
        <>
            <header className="hero">
                <div className="hero-copy-block">
                    <div className="hero-kicker">로컬 크리에이터 워크벤치</div>
                    <h1>프롬프트에서 쇼츠 설계까지 한 화면에서 정리하는 스튜디오</h1>
                    <p className="hero-copy">
                        텍스트 입력, 장면 라우팅, 저장 경로, 실제 초안 렌더까지 지금 단계에서 필요한
                        작업 흐름만 남기고 재정리했습니다. 엔지니어용 대시보드가 아니라 제작자가 보는
                        작업실에 가깝게 맞춘 상태입니다.
                    </p>
                    <div className="hero-tags">
                        <span>로컬 브리지</span>
                        <span>장면별 고급 생성 라우팅</span>
                        <span>실제 초안 렌더</span>
                    </div>
                </div>

                <div className="hero-signal">
                    <div className="signal-card">
                        <span className="signal-label">브리지</span>
                        <strong>{bridgeSummary(bridgeStatus, bridgeHealth)}</strong>
                        <small>{bridgeMessage}</small>
                    </div>
                    <div className="signal-card">
                        <span className="signal-label">프리미엄 장면</span>
                        <strong>{premiumSceneCount}</strong>
                        <small>현재 초안 기준 고급 생성 경로 수</small>
                    </div>
                    <div className="signal-card">
                        <span className="signal-label">예상 길이</span>
                        <strong>{selectedProject?.manifest.totalDurationSec.toFixed(1) ?? "0.0"}초</strong>
                        <small>선택된 프로젝트의 샘플 타임라인</small>
                    </div>
                    <div className="signal-card">
                        <span className="signal-label">장면 자산</span>
                        <strong>{selectedProjectAssetCount}</strong>
                        <small>현재 선택된 초안에 세션 중 연결한 파일 수</small>
                    </div>
                </div>
            </header>

            <section className="panel composer-panel">
                <div className="panel-header">
                    <span className="panel-index">01</span>
                    <div>
                        <h2>제작 브리프</h2>
                        <p>무엇을 만들고 싶은지 적으면, 장면 흐름과 렌더 경로를 먼저 설계합니다.</p>
                    </div>
                </div>

                <div className="workflow-strip">
                    <span>1. 브리지 상태 확인</span>
                    <span>2. 프롬프트 작성</span>
                    <span>3. 초안 생성</span>
                    <span>4. 저장 또는 초안 렌더</span>
                </div>

                <label className="field">
                    <span>어떤 영상을 만들고 싶은가요?</span>
                    <textarea
                        value={prompt}
                        onChange={(event) => onPromptChange(event.target.value)}
                        rows={7}
                        placeholder="예: 차분한 카페 분위기의 30초 인스타 릴스, 여성 나레이션, 첫 장면은 고급스럽게"
                    />
                </label>

                <div className="chip-row">
                    {samplePrompts.map((item) => (
                        <button key={item} className="chip" type="button" onClick={() => onPromptChange(item)}>
                            {item}
                        </button>
                    ))}
                </div>

                <div className="control-grid">
                    <label className="field compact">
                        <span>예산 모드</span>
                        <select value={budgetMode} onChange={(event) => onBudgetModeChange(event.target.value as BudgetMode)}>
                            <option value="free">무료</option>
                            <option value="standard">표준</option>
                            <option value="premium">프리미엄</option>
                        </select>
                    </label>

                    <label className="field compact">
                        <span>월 예산 상한 (USD)</span>
                        <input
                            type="number"
                            min={0}
                            step={5}
                            value={monthlyCapUsd}
                            onChange={(event) => onMonthlyCapUsdChange(Number(event.target.value))}
                        />
                    </label>
                </div>

                <div className="toggle-grid">
                    <label className="toggle">
                        <input type="checkbox" checked={preferBridge} onChange={(event) => onPreferBridgeChange(event.target.checked)} />
                        <span>브리지 연결 시 worker를 우선 사용</span>
                    </label>
                    <label className="toggle">
                        <input
                            type="checkbox"
                            checked={availability.premiumEnabled}
                            onChange={(event) => onAvailabilityChange((current) => ({ ...current, premiumEnabled: event.target.checked }))}
                        />
                        <span>프리미엄 장면 라우팅 사용</span>
                    </label>
                    <label className="toggle">
                        <input
                            type="checkbox"
                            checked={availability.sora2}
                            onChange={(event) => onAvailabilityChange((current) => ({ ...current, sora2: event.target.checked }))}
                        />
                        <span>Sora 2 경로 허용</span>
                    </label>
                    <label className="toggle">
                        <input
                            type="checkbox"
                            checked={availability.veo3}
                            onChange={(event) => onAvailabilityChange((current) => ({ ...current, veo3: event.target.checked }))}
                        />
                        <span>Veo 3 경로 허용</span>
                    </label>
                </div>

                <div className="bridge-banner">
                    <div>
                        <span className="summary-label">런타임 상태</span>
                        <strong>{bridgeSummary(bridgeStatus, bridgeHealth)}</strong>
                    </div>
                    <button className="subtle-button" type="button" onClick={onRefreshBridge}>
                        브리지 다시 확인
                    </button>
                </div>

                <p className="bridge-message">{bridgeMessage}</p>

                <button className="action-button" type="button" onClick={onGenerate}>
                    {isGenerating ? "초안을 생성하는 중..." : "스토리보드 초안 만들기"}
                </button>
            </section>
        </>
    );
}
