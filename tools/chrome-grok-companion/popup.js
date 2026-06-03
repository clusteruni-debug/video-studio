const commandUrlEl = document.getElementById("commandUrl");
const promptPreviewEl = document.getElementById("promptPreview");
const statusEl = document.getElementById("status");
const autoQueueEl = document.getElementById("autoQueue");
let command = null;

function setStatus(value) {
  statusEl.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

async function activeTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs[0] || null;
}

async function waitForTabComplete(tabId, timeoutMs = 15000) {
  const existing = await chrome.tabs.get(tabId).catch(() => null);
  if (existing?.status === "complete") return existing;
  return new Promise((resolve) => {
    const timeout = setTimeout(async () => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve(await chrome.tabs.get(tabId).catch(() => null));
    }, timeoutMs);
    const listener = async (updatedTabId, changeInfo) => {
      if (updatedTabId !== tabId || changeInfo.status !== "complete") return;
      clearTimeout(timeout);
      chrome.tabs.onUpdated.removeListener(listener);
      resolve(await chrome.tabs.get(tabId).catch(() => null));
    };
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function ensureGrokTab() {
  if (!command) await loadCommand();
  const grokUrl = command.grokUrl || "https://grok.com/imagine";
  const tabs = await chrome.tabs.query({ currentWindow: true });
  let tab = tabs.find((item) => String(item.url || "").includes("grok.com"));
  if (!tab) {
    tab = await chrome.tabs.create({ url: grokUrl, active: true });
  } else {
    await chrome.tabs.update(tab.id, { active: true });
  }
  await waitForTabComplete(tab.id);
  return chrome.tabs.get(tab.id);
}

async function sendToTab(tab, type) {
  if (!command) throw new Error("Load a command URL first.");
  return chrome.tabs.sendMessage(tab.id, { type, command });
}

async function sendToContent(type) {
  if (!command) throw new Error("Load a command URL first.");
  let tab = await activeTab();
  if (!tab || !String(tab.url || "").includes("grok.com")) {
    tab = await chrome.tabs.create({ url: command.grokUrl || "https://grok.com/imagine", active: true });
    setStatus("Opened Grok. Run the action again after the page finishes loading.");
    return null;
  }
  return chrome.tabs.sendMessage(tab.id, { type, command });
}

async function reportContentResult(eventType, result, successStatus, fallbackDetail) {
  if (!result) return;
  const modeDetail = result.mode?.status ? ` / mode=${result.mode.status}:${result.mode.label || ""}` : "";
  await report({
    eventType,
    status: result.ok ? successStatus : "failed",
    detail: `${result.label || result.error || fallbackDetail}${modeDetail}`,
    currentUrl: result.currentUrl
  });
}

async function report(event) {
  await chrome.runtime.sendMessage({ type: "extension-event", command, event });
}

async function loadStoredCommandUrl() {
  const data = await chrome.storage.local.get("videoStudioGrokCommandUrl");
  if (data.videoStudioGrokCommandUrl) commandUrlEl.value = data.videoStudioGrokCommandUrl;
}

async function loadAutoQueueSetting() {
  const result = await chrome.runtime.sendMessage({ type: "get-auto-queue" }).catch(() => null);
  autoQueueEl.checked = result?.enabled === true;
  return autoQueueEl.checked;
}

async function loadCommand() {
  const url = commandUrlEl.value.trim();
  if (!url) throw new Error("Command URL is required.");
  await chrome.storage.local.set({ videoStudioGrokCommandUrl: url });
  const response = await fetch(url);
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "Command load failed.");
  command = data;
  promptPreviewEl.value = data.prompt || "";
  await chrome.runtime.sendMessage({ type: "store-command", command });
  const autoQueue = await loadAutoQueueSetting();
  setStatus({
    sceneId: data.sceneId,
    expectedFileName: data.expectedFileName,
    downloadDir: data.defaultDownloadDir,
    autoImport: Boolean(data.importEndpoint),
    autoQueue,
    missingSceneIds: data.missingSceneIds || [],
    rejectedSceneIds: data.rejectedSceneIds || [],
    nextMissingSceneId: data.nextMissingSceneId || "",
    queueReady: Boolean(data.queueCommandUrl),
    guardrails: data.guardrails
  });
}

async function loadNextScene() {
  if (!command) await loadCommand();
  const url = command.queueCommandUrl || command.nextCommandUrl;
  if (!url) throw new Error("This command does not include a scene queue URL.");
  commandUrlEl.value = url;
  await loadCommand();
}

document.getElementById("pasteCommand").addEventListener("click", async () => {
  commandUrlEl.value = await navigator.clipboard.readText();
});

document.getElementById("loadCommand").addEventListener("click", async () => {
  try {
    await loadCommand();
  } catch (error) {
    setStatus(String(error.message || error));
  }
});

document.getElementById("loadNextScene").addEventListener("click", async () => {
  try {
    await loadNextScene();
  } catch (error) {
    setStatus(String(error.message || error));
  }
});

document.getElementById("openGrok").addEventListener("click", async () => {
  try {
    if (!command) await loadCommand();
    await chrome.tabs.create({ url: command.grokUrl || "https://grok.com/imagine", active: true });
  } catch (error) {
    setStatus(String(error.message || error));
  }
});

document.getElementById("fillPrompt").addEventListener("click", async () => {
  try {
    if (!command) await loadCommand();
    const result = await sendToContent("fill-prompt");
    await reportContentResult("prompt-fill", result, "filled", "Prompt filled.");
    setStatus(result || "Grok tab opened.");
  } catch (error) {
    setStatus(String(error.message || error));
  }
});

document.getElementById("prepGenerate").addEventListener("click", async () => {
  try {
    if (!command) await loadCommand();
    const tab = await ensureGrokTab();
    setStatus(`Preparing ${command.sceneId || "scene"} in Grok...`);
    const fillResult = await sendToTab(tab, "fill-prompt");
    await reportContentResult("prompt-fill", fillResult, "filled", "Prompt filled.");
    if (!fillResult?.ok) {
      setStatus(fillResult);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 450));
    const generateResult = await sendToTab(tab, "click-generate");
    await reportContentResult("generate-click", generateResult, "clicked", "Generate requested.");
    setStatus({
      sceneId: command.sceneId,
      expectedFileName: command.expectedFileName,
      fill: fillResult,
      generate: generateResult,
      mode: generateResult?.mode || fillResult?.mode || null,
      nextStep: "After Grok finishes, use Import MP4. Direct .mp4 URLs upload to Video Studio without Chrome's save prompt; if direct import fails, use Video Studio manual batch upload."
    });
  } catch (error) {
    setStatus(String(error.message || error));
  }
});

document.getElementById("clickGenerate").addEventListener("click", async () => {
  try {
    if (!command) await loadCommand();
    const result = await sendToContent("click-generate");
    await reportContentResult("generate-click", result, "clicked", "Generate requested.");
    setStatus(result || "Grok tab opened.");
  } catch (error) {
    setStatus(String(error.message || error));
  }
});

document.getElementById("clickDownload").addEventListener("click", async () => {
  try {
    if (!command) await loadCommand();
    const result = await sendToContent("click-download");
    const candidateMeta = (candidate = {}) => ({
      sourceKind: candidate.sourceKind || "",
      videoWidth: candidate.videoWidth ?? "",
      videoHeight: candidate.videoHeight ?? "",
      qualityFloorMet: candidate.qualityFloorMet ?? "",
      qualityNote: candidate.qualityNote || ""
    });
    if (result?.downloadClicked) {
      const candidate = result.videoCandidates?.[0] || {};
      await report({
        eventType: "download-click",
        status: "clicked",
        detail: result.downloadKind || result.label || "Download requested.",
        currentUrl: result.currentUrl,
        candidateUrl: candidate.url || "",
        sourceKind: result.sourceKind || candidate.sourceKind || "",
        videoWidth: result.videoWidth ?? candidate.videoWidth ?? "",
        videoHeight: result.videoHeight ?? candidate.videoHeight ?? "",
        qualityFloorMet: result.qualityFloorMet ?? candidate.qualityFloorMet ?? "",
        qualityNote: result.qualityNote || candidate.qualityNote || ""
      });
    } else if (result?.directImport) {
      const candidate = result.videoCandidates?.[0] || {};
      await report({
        eventType: "video-candidate",
        status: "direct-imported",
        detail: `${result.directImportKind || "companion-direct-import"}; next=${result.nextSceneId || ""}; autoQueue=${result.autoQueue || "off"}; ${result.queueError || ""}`,
        currentUrl: result.currentUrl,
        candidateUrl: result.candidateUrl || candidate.url || "",
        sourceKind: "visible-video-blob-direct-fetch",
        videoWidth: candidate.videoWidth ?? "",
        videoHeight: candidate.videoHeight ?? "",
        qualityFloorMet: candidate.qualityFloorMet ?? "",
        qualityNote: candidate.qualityNote
          ? `${candidate.qualityNote}; companion-blob-direct-fetch; no-browser-download-prompt`
          : "companion-blob-direct-fetch; no-browser-download-prompt"
      });
    } else if (result?.directImportOnly) {
      await report({
        eventType: "video-candidate",
        status: "manual-fallback-required",
        detail: result.error || "direct import could not see a Grok .mp4 URL; do not auto-click browser download",
        currentUrl: result.currentUrl,
        sourceKind: "direct-import-only",
        qualityNote: "no-browser-download-auto-click"
      });
    } else if (result?.videoCandidates?.length) {
      const candidate = result.videoCandidates.find((item) => item.kind === "url") || result.videoCandidates[0];
      const lowQualityVisibleFallback = candidate.sourceKind === "visible-video-fallback" && candidate.qualityFloorMet === false;
      if (candidate.kind === "url" && !lowQualityVisibleFallback) {
        const importResult = await chrome.runtime.sendMessage({
          type: "download-candidate",
          command,
          candidateUrl: candidate.url,
          currentUrl: result.currentUrl || "",
          sourceKind: candidate.sourceKind || "",
          videoWidth: candidate.videoWidth ?? "",
          videoHeight: candidate.videoHeight ?? "",
          qualityFloorMet: candidate.qualityFloorMet ?? "",
          qualityNote: candidate.qualityNote || ""
        });
        result.directImport = importResult?.directImport === true;
        result.importResult = importResult;
        result.importError = result.directImport ? "" : importResult?.error || "direct import failed";
        result.importBlocked = importResult?.blocked === true || !result.directImport;
        result.downloadCandidate = candidate;
      }
      await report({
        eventType: "video-candidate",
        status: lowQualityVisibleFallback
          ? "blocked"
          : (result.importError ? "failed" : result.directImport ? "direct-imported" : "manual-fallback-required"),
        detail: lowQualityVisibleFallback
          ? "visible-video-fallback-proof-only; use Companion/pageAssets direct import or operator-owned manual upload for original MP4"
          : (result.importError || (result.directImport ? "companion-direct-import" : candidate.kind)),
        currentUrl: result.currentUrl,
        candidateUrl: candidate.url,
        ...candidateMeta(candidate)
      });
    } else if (result) {
      await report({ eventType: "download-click", status: result.ok ? "clicked" : "failed", detail: result.label || result.error || "Download requested.", currentUrl: result.currentUrl });
    }
    setStatus(result || "Grok tab opened.");
  } catch (error) {
    setStatus(String(error.message || error));
  }
});

document.getElementById("probePage").addEventListener("click", async () => {
  try {
    if (!command) await loadCommand();
    const result = await sendToContent("probe");
    if (result) await report({ eventType: "probe", status: result.ok ? "ready" : "failed", detail: `editable=${result.editableCount || 0}; videos=${(result.videoCandidates || []).length}`, currentUrl: result.currentUrl });
    setStatus(result || "Grok tab opened.");
  } catch (error) {
    setStatus(String(error.message || error));
  }
});

autoQueueEl.addEventListener("change", async () => {
  const result = await chrome.runtime.sendMessage({
    type: "set-auto-queue",
    enabled: autoQueueEl.checked
  }).catch((error) => ({ ok: false, error: String(error?.message || error) }));
  setStatus({
    autoQueue: result?.enabled === true,
    nextStep: result?.enabled
      ? "After a completed MP4 import, the extension will load the next scene command and run Prep + Generate."
      : "Auto queue is off; use Next scene manually after each import.",
    error: result?.error || ""
  });
});

loadStoredCommandUrl();
loadAutoQueueSetting();
