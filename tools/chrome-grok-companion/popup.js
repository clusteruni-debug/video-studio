const commandUrlEl = document.getElementById("commandUrl");
const promptPreviewEl = document.getElementById("promptPreview");
const statusEl = document.getElementById("status");
const autoQueueEl = document.getElementById("autoQueue");
let command = null;
const PROVIDER_CAPABILITIES = Object.freeze({
  "grok-web-video": Object.freeze({
    canUsePopupControls: true,
    canFillPrompt: true,
    canClickGenerate: true,
    canImportResult: true
  }),
  "gemini-web-image": Object.freeze({
    canUsePopupControls: false,
    canFillPrompt: true,
    canClickGenerate: false,
    canImportResult: false
  })
});

function setStatus(value) {
  statusEl.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function commandProvider() {
  return String(command?.provider || "grok-web-video");
}

function providerCapabilities() {
  return PROVIDER_CAPABILITIES[commandProvider()] || null;
}

function assertGrokPopupControls() {
  const capabilities = providerCapabilities();
  if (!capabilities?.canUsePopupControls) {
    throw new Error(`Popup controls are Grok-only for now. Use the ${commandProvider()} autostartUrl; Gemini Generate/import remains operator-owned.`);
  }
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

function isImagineTabUrl(url) {
  try {
    const parsed = new URL(String(url || ""));
    const pathname = parsed.pathname.toLowerCase();
    return parsed.hostname.endsWith("grok.com")
      && pathname.startsWith("/imagine")
      && !pathname.startsWith("/imagine/post");
  } catch (error) {
    return false;
  }
}

function isGrokTabUrl(url) {
  try {
    const parsed = new URL(String(url || ""));
    return parsed.hostname.endsWith("grok.com");
  } catch (error) {
    return false;
  }
}

function imagineUrlForCommand() {
  const value = String(command?.grokUrl || "");
  return isImagineTabUrl(value) ? value : "https://grok.com/imagine";
}

function contentScriptForTab(tab) {
  try {
    const parsed = new URL(String(tab?.url || ""));
    if (parsed.hostname.endsWith("grok.com")) return "content.js";
    if (isGeminiTabHost(parsed.hostname)) return "content_gemini.js";
  } catch (error) {
    return "";
  }
  return "";
}

function describeTabUrl(tab) {
  return String(tab?.url || "").slice(0, 180);
}

function isGeminiTabHost(hostname) {
  const value = String(hostname || "").toLowerCase();
  return value === "gemini.google.com" || /^gemini\.google-[a-z0-9-]+\.com$/.test(value);
}

function isReceivingEndError(error) {
  return /receiving end does not exist|could not establish connection/i.test(String(error?.message || error || ""));
}

async function injectContentScript(tab) {
  const file = contentScriptForTab(tab);
  if (!file || !tab?.id || !chrome.scripting?.executeScript) return false;
  await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: [file] });
  await new Promise((resolve) => setTimeout(resolve, 350));
  return true;
}

async function sendMessageWithInjection(tab, message) {
  try {
    return await chrome.tabs.sendMessage(tab.id, message);
  } catch (error) {
    if (!isReceivingEndError(error) || !(await injectContentScript(tab))) {
      throw error;
    }
    return chrome.tabs.sendMessage(tab.id, message);
  }
}

async function ensureGrokTab() {
  if (!command) await loadCommand();
  const current = await activeTab();
  if (isImagineTabUrl(current?.url)) {
    await waitForTabComplete(current.id);
    const refreshed = await chrome.tabs.get(current.id);
    if (isImagineTabUrl(refreshed?.url)) return refreshed;
    throw new Error(`Grok left Imagine after loading: ${describeTabUrl(refreshed)}. Open the actual Imagine composer, then press Prep + Generate again.`);
  }
  const tabs = await chrome.tabs.query({ currentWindow: true });
  const tab = tabs.find((item) => isImagineTabUrl(item.url));
  if (!tab) {
    throw new Error("No active Grok Imagine composer tab found. Open the real Grok Imagine composer first; Prep + Generate will not auto-open /imagine because Grok can redirect it to /c chat.");
  }
  await chrome.tabs.update(tab.id, { active: true });
  await waitForTabComplete(tab.id);
  const refreshed = await chrome.tabs.get(tab.id);
  if (!isImagineTabUrl(refreshed?.url)) {
    throw new Error(`Grok tab is not on the Imagine composer: ${describeTabUrl(refreshed)}. Open Imagine manually and retry.`);
  }
  return refreshed;
}

async function sendToTab(tab, type) {
  if (!command) throw new Error("Load a command URL first.");
  return sendMessageWithInjection(tab, { type, command });
}

async function sendToContent(type, options = {}) {
  if (!command) throw new Error("Load a command URL first.");
  let tab = await activeTab();
  const requireImagine = options.requireImagine === true;
  const usableTab = requireImagine ? isImagineTabUrl(tab?.url) : isGrokTabUrl(tab?.url);
  if (!tab || !usableTab) {
    if (requireImagine) {
      setStatus("Open the actual Grok Imagine composer tab first. This control no longer auto-opens /imagine because Grok can redirect it to /c chat.");
      return null;
    }
    tab = await chrome.tabs.create({ url: command.grokUrl || "https://grok.com/imagine", active: true });
    setStatus("Opened Grok. Run the action again after the page finishes loading.");
    return null;
  }
  return sendMessageWithInjection(tab, { type, command });
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
  await chrome.runtime.sendMessage({ type: "store-command", command, commandUrl: url });
  const autoQueue = await loadAutoQueueSetting();
  setStatus({
    provider: data.provider || "grok-web-video",
    sceneId: data.sceneId,
    cutId: data.cutId || "",
    expectedFileName: data.expectedFileName,
    downloadDir: data.defaultDownloadDir,
    autoImport: Boolean(data.importEndpoint),
    autoQueue,
    capabilities: providerCapabilities(),
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
    assertGrokPopupControls();
    await chrome.tabs.create({ url: command.grokUrl || "https://grok.com/imagine", active: true });
  } catch (error) {
    setStatus(String(error.message || error));
  }
});

document.getElementById("fillPrompt").addEventListener("click", async () => {
  try {
    if (!command) await loadCommand();
    assertGrokPopupControls();
    const result = await sendToContent("fill-prompt", { requireImagine: true });
    await reportContentResult("prompt-fill", result, "filled", "Prompt filled.");
    setStatus(result || "Grok tab opened.");
  } catch (error) {
    setStatus(String(error.message || error));
  }
});

document.getElementById("prepGenerate").addEventListener("click", async () => {
  try {
    if (!command) await loadCommand();
    assertGrokPopupControls();
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
    assertGrokPopupControls();
    const result = await sendToContent("click-generate", { requireImagine: true });
    await reportContentResult("generate-click", result, "clicked", "Generate requested.");
    setStatus(result || "Grok tab opened.");
  } catch (error) {
    setStatus(String(error.message || error));
  }
});

document.getElementById("clickDownload").addEventListener("click", async () => {
  try {
    if (!command) await loadCommand();
    assertGrokPopupControls();
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
          ? "visible-video-fallback-proof-only; use operator-owned download/import or manual upload for original MP4"
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
    assertGrokPopupControls();
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
