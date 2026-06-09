const STORAGE_KEY = "videoStudioGrokCommand";
const COMMAND_URL_KEY = "videoStudioGrokCommandUrl";
const AUTO_QUEUE_KEY = "videoStudioGrokAutoQueueEnabled";
const KEEPALIVE_ALARM_NAME = "videoStudioGrokCompanionKeepalive";
const KEEPALIVE_PERIOD_MINUTES = 1;
const EXTENSION_BUILD_TAG = "20260607-popup-state-fix";
const handledAutostartKeys = new Set();
const PROVIDER_CAPABILITIES = Object.freeze({
  "grok-web-video": Object.freeze({
    canProbe: true,
    canFillPrompt: true,
    canClickGenerate: true,
    canImportResult: true,
    canGenerateVideo: true
  }),
  "gemini-web-image": Object.freeze({
    canProbe: true,
    canFillPrompt: true,
    canClickGenerate: false,
    canImportResult: false,
    canGenerateVideo: false
  })
});

// SSRF guard: command payloads may only be fetched from the local bridge origin.
// Must match the extension manifest host_permissions (127.0.0.1:5161 only).
const BRIDGE_ALLOWED_ORIGINS = new Set([
  "http://127.0.0.1:5161",
]);

async function getStoredCommand() {
  const data = await chrome.storage.local.get(STORAGE_KEY);
  return data[STORAGE_KEY] || null;
}

async function setStoredCommand(command) {
  await chrome.storage.local.set({ [STORAGE_KEY]: command });
}

async function setStoredCommandUrl(url) {
  if (url) await chrome.storage.local.set({ [COMMAND_URL_KEY]: url });
}

async function getAutoQueueEnabled() {
  const data = await chrome.storage.local.get(AUTO_QUEUE_KEY);
  return data[AUTO_QUEUE_KEY] === true;
}

async function setAutoQueueEnabled(enabled) {
  await chrome.storage.local.set({ [AUTO_QUEUE_KEY]: enabled === true });
}

function extensionVersion() {
  try {
    return chrome.runtime.getManifest().version || "";
  } catch (error) {
    return "";
  }
}

function extensionBuildDetail() {
  return `version=${extensionVersion()} build=${EXTENSION_BUILD_TAG}`;
}

function commandProvider(command) {
  return String(command?.provider || "grok-web-video");
}

function providerCapabilities(command) {
  return PROVIDER_CAPABILITIES[commandProvider(command)] || null;
}

function capabilityForAction(action) {
  if (action === "probe") return "canProbe";
  if (action === "fill-prompt" || action === "prep-generate") return "canFillPrompt";
  if (action === "click-generate") return "canClickGenerate";
  if (["download-asset", "download-visible-video", "download-post-video", "download-current-video"].includes(action)) return "canImportResult";
  return "";
}

function assertProviderAction(command, action) {
  const capabilities = providerCapabilities(command);
  if (!capabilities) {
    throw new Error(`unsupported companion provider: ${commandProvider(command)}`);
  }
  const capability = capabilityForAction(action);
  if (!capability || capabilities[capability] !== true) {
    throw new Error(`companion action not supported for provider=${commandProvider(command)} action=${action}`);
  }
}

async function loadCommandFromUrl(url) {
  if (!url) return null;
  let parsed;
  try {
    parsed = new URL(url);
  } catch (error) {
    throw new Error(`refusing to load command from invalid URL: ${url}`);
  }
  if (!BRIDGE_ALLOWED_ORIGINS.has(parsed.origin)) {
    throw new Error(`refusing to load command from non-bridge origin: ${parsed.origin}`);
  }
  const response = await fetch(parsed.href);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `command load failed: HTTP ${response.status}`);
  }
  await setStoredCommand(data);
  await setStoredCommandUrl(url);
  return data;
}

async function postBridgeEvent(endpoint, payload) {
  let parsed;
  try {
    parsed = new URL(String(endpoint || ""));
  } catch (error) {
    throw new Error(`refusing to post event to invalid URL: ${endpoint}`);
  }
  if (!BRIDGE_ALLOWED_ORIGINS.has(parsed.origin)) {
    throw new Error(`refusing to post event to non-bridge origin: ${parsed.origin}`);
  }
  const response = await fetch(parsed.href, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {})
  });
  if (!response.ok) {
    throw new Error(`bridge event post failed: HTTP ${response.status}`);
  }
  return response.json().catch(() => ({}));
}

async function postEvent(command, event) {
  if (!command || !command.eventEndpoint) return;
  const payload = {
    operatorApproved: true,
    extensionApproved: true,
    provider: event.provider || command.provider || "",
    projectId: command.projectId,
    episodeId: command.episodeId || "",
    batchId: command.batchId || "",
    cutId: command.cutId || "",
    sceneId: command.sceneId,
    expectedFileName: command.expectedFileName,
    currentUrl: event.currentUrl || "",
    candidateUrl: event.candidateUrl || "",
    sourceKind: event.sourceKind || "",
    videoWidth: event.videoWidth ?? "",
    videoHeight: event.videoHeight ?? "",
    qualityFloorMet: event.qualityFloorMet ?? "",
    qualityNote: event.qualityNote || "",
    eventType: event.eventType || "extension-event",
    status: event.status || "reported",
    detail: event.detail || ""
  };
  try {
    await fetch(command.eventEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    console.warn("Video Studio event post failed", error);
  }
}

async function postHeartbeat(command, detail = "Chrome companion connected.") {
  await postEvent(command, {
    eventType: "companion-heartbeat",
    status: "connected",
    detail: `${detail} ${extensionBuildDetail()}`,
  });
}

async function postStoredHeartbeat(detail = "Chrome companion keepalive.") {
  const command = await getStoredCommand();
  if (!command) return;
  await postHeartbeat(command, detail);
}

async function ensureKeepaliveAlarm() {
  if (!chrome.alarms?.create) return;
  await chrome.alarms.create(KEEPALIVE_ALARM_NAME, {
    delayInMinutes: KEEPALIVE_PERIOD_MINUTES,
    periodInMinutes: KEEPALIVE_PERIOD_MINUTES,
  });
}

function autostartRequestFromUrl(url) {
  let parsed;
  try {
    parsed = new URL(String(url || ""));
  } catch (error) {
    return null;
  }
  if (!parsed.hostname.endsWith("grok.com")) return null;
  const rawHash = String(parsed.hash || "").replace(/^#/, "");
  if (!rawHash) return null;
  const params = new URLSearchParams(rawHash);
  const commandUrl = params.get("videoStudioGrokCommandUrl") || params.get("vsCommandUrl") || "";
  if (!commandUrl) return null;
  const action = params.get("videoStudioAction") || "fill-prompt";
  return {
    commandUrl,
    action,
    operatorApproved: params.get("operatorApproved") === "true",
    autoGenerate: params.get("videoStudioAutoGenerate") === "true" || action === "prep-generate",
  };
}

function mp4AssetCandidateFromUrl(url) {
  const value = String(url || "");
  const cleanUrl = value.split("#")[0];
  let parsed;
  try {
    parsed = new URL(cleanUrl);
  } catch (error) {
    return "";
  }
  if (!parsed.hostname.endsWith("grok.com")) return "";
  if (!parsed.pathname.toLowerCase().endsWith(".mp4")) return "";
  return cleanUrl;
}

function safeDownloadFilename(filename) {
  const value = String(filename || "").trim();
  const basename = value.split(/[\\/]/).filter(Boolean).pop() || "grok-video.mp4";
  return basename.toLowerCase().endsWith(".mp4") ? basename : `${basename}.mp4`;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    const chunk = bytes.subarray(offset, offset + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

async function importCandidateUrl(command, candidateUrl, currentUrl, eventType = "companion-direct-import", eventMeta = {}) {
  const cleanCandidateUrl = mp4AssetCandidateFromUrl(candidateUrl);
  if (!cleanCandidateUrl) {
    throw new Error("direct import requires a Grok .mp4 asset URL.");
  }
  if (!command?.uploadEndpoint) {
    return null;
  }
  if (!command?.sceneId) {
    throw new Error("sceneId is required before direct Grok MP4 import.");
  }
  const filename = safeDownloadFilename(command.expectedFileName || "grok-video.mp4");
  const sourceKind = eventMeta.sourceKind || "companion-direct-fetch";
  const qualityNote = eventMeta.qualityNote || "original-download-source; companion-direct-fetch; no-browser-download-prompt";
  const response = await fetch(cleanCandidateUrl, {
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`direct MP4 fetch failed: HTTP ${response.status}`);
  }
  const buffer = await response.arrayBuffer();
  if (!buffer.byteLength) {
    throw new Error("direct MP4 fetch returned an empty file.");
  }
  const uploadResponse = await fetch(command.uploadEndpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      operatorApproved: true,
      extensionApproved: true,
      directImportProof: true,
      eventType,
      sceneId: command.sceneId,
      expectedFileName: command.expectedFileName || filename,
      fileName: filename,
      fileBase64: arrayBufferToBase64(buffer),
      currentUrl,
      candidateUrl: cleanCandidateUrl,
      sourceKind,
      videoWidth: eventMeta.videoWidth ?? "",
      videoHeight: eventMeta.videoHeight ?? "",
      qualityFloorMet: eventMeta.qualityFloorMet ?? "",
      qualityNote,
      overwrite: false,
      preserveCandidates: true,
    }),
  });
  const imported = await uploadResponse.json().catch(() => ({}));
  if (!uploadResponse.ok || imported.ok === false) {
    throw new Error(imported.error || `direct MP4 import failed: HTTP ${uploadResponse.status}`);
  }
  await postEvent(command, {
    eventType,
    status: (imported.imported || []).length ? "imported" : "no-match",
    detail: `direct bridge import; bytes=${buffer.byteLength}; imported=${(imported.imported || []).length}`,
    currentUrl,
    candidateUrl: cleanCandidateUrl,
    sourceKind,
    videoWidth: eventMeta.videoWidth ?? "",
    videoHeight: eventMeta.videoHeight ?? "",
    qualityFloorMet: eventMeta.qualityFloorMet ?? "",
    qualityNote,
  });
  const nextCommand = await advanceToNextScene(command, imported);
  let autoQueueResult = null;
  let autoQueueState = "off";
  if (nextCommand && (await getAutoQueueEnabled())) {
    try {
      autoQueueResult = await prepGenerateNextScene(nextCommand, command);
      autoQueueState = autoQueueResult ? "attempted" : "off";
    } catch (error) {
      autoQueueState = "failed";
      await postEvent(nextCommand, {
        eventType: "auto-queue",
        status: "failed",
        detail: String(error && error.message ? error.message : error),
        candidateUrl: cleanCandidateUrl,
      });
    }
  }
  return {
    directImport: true,
    candidateUrl: cleanCandidateUrl,
    filename,
    imported,
    nextSceneId: nextCommand?.sceneId || imported.nextMissingSceneId || "",
    autoQueue: autoQueueState,
    autoQueueResult,
  };
}

async function downloadAssetUrl(command, candidateUrl, currentUrl, eventType = "background-autostart-download", eventMeta = {}) {
  const cleanCandidateUrl = mp4AssetCandidateFromUrl(candidateUrl);
  if (!cleanCandidateUrl) {
    throw new Error("download-candidate action requires a Grok .mp4 asset URL.");
  }
  if (command?.uploadEndpoint) {
    return importCandidateUrl(command, cleanCandidateUrl, currentUrl, eventType, eventMeta);
  }
  await postEvent(command, {
    eventType,
    status: "blocked",
    detail: "download-candidate requires local uploadEndpoint; native browser download fallback disabled",
    currentUrl,
    candidateUrl: cleanCandidateUrl,
    sourceKind: eventMeta.sourceKind || "",
    videoWidth: eventMeta.videoWidth ?? "",
    videoHeight: eventMeta.videoHeight ?? "",
    qualityFloorMet: eventMeta.qualityFloorMet ?? "",
    qualityNote: eventMeta.qualityNote || "",
  });
  return {
    ok: false,
    blocked: true,
    candidateUrl: cleanCandidateUrl,
    error: "uploadEndpoint-required-no-browser-download-fallback",
  };
}

async function downloadAssetFromCurrentTab(command, currentUrl) {
  const candidateUrl = mp4AssetCandidateFromUrl(currentUrl);
  if (!candidateUrl) {
    throw new Error("download-asset action requires the current tab URL to be a direct .mp4 asset.");
  }
  return downloadAssetUrl(command, candidateUrl, currentUrl, "background-autostart-download", {
    sourceKind: "direct-mp4-asset-tab",
    qualityFloorMet: null,
    qualityNote: "original-download-source",
  });
}

function directAutostartEventTarget(request) {
  try {
    const commandUrl = new URL(request.commandUrl);
    // SSRF guard at the sink: never build an event endpoint for a non-bridge
    // origin, so no caller (including the error path in runAutostartFromTabUrl)
    // can POST to an attacker-controlled host.
    if (!BRIDGE_ALLOWED_ORIGINS.has(commandUrl.origin)) return null;
    const parts = commandUrl.pathname.split("/").filter(Boolean);
    const handoffIndex = parts.indexOf("grok-handoff");
    const projectId = handoffIndex >= 0 ? parts[handoffIndex + 1] : "";
    if (!projectId) return null;
    return {
      endpoint: `${commandUrl.origin}/api/grok-handoff/${encodeURIComponent(projectId)}/extension-event`,
      sceneId: commandUrl.searchParams.get("sceneId") || "",
    };
  } catch (error) {
    return null;
  }
}

async function postDirectAutostartEvent(request, event) {
  const target = directAutostartEventTarget(request);
  if (!target) return;
  try {
    await fetch(target.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operatorApproved: true,
        extensionApproved: true,
        source: "chrome-companion-background",
        sceneId: target.sceneId,
        expectedFileName: event.expectedFileName || "",
        currentUrl: event.currentUrl || "",
        candidateUrl: event.candidateUrl || "",
        sourceKind: event.sourceKind || "",
        videoWidth: event.videoWidth ?? "",
        videoHeight: event.videoHeight ?? "",
        qualityFloorMet: event.qualityFloorMet ?? "",
        qualityNote: event.qualityNote || "",
        eventType: event.eventType || "background-autostart",
        status: event.status || "reported",
        detail: event.detail || "",
      }),
    });
  } catch (error) {
    console.warn("Video Studio background autostart report failed", error);
  }
}

function directoryFromFilename(filename) {
  const value = String(filename || "");
  const slash = Math.max(value.lastIndexOf("\\"), value.lastIndexOf("/"));
  return slash >= 0 ? value.slice(0, slash) : "";
}

async function importDownloadedMp4(command, filename) {
  if (!command || !command.importEndpoint) return null;
  const downloadDir = directoryFromFilename(filename) || command.defaultDownloadDir || "";
  if (!downloadDir) {
    await postEvent(command, {
      eventType: "auto-import",
      status: "skipped",
      detail: "Download directory unavailable; use Video Studio Downloads import.",
    });
    return null;
  }
  const response = await fetch(command.importEndpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      operatorApproved: true,
      extensionApproved: true,
      sceneId: command.sceneId,
      downloadDir,
      downloadFilePath: filename,
      allowNewestFallback: true,
      overwrite: true,
      preserveCandidates: true,
      sinceHandoff: true,
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `import failed: HTTP ${response.status}`);
  }
  return payload;
}

async function advanceToNextScene(command, imported) {
  if (!command || !command.queueCommandUrl || !imported || imported.allReady) return null;
  const importedCount = (imported.imported || []).length;
  if (!importedCount) return null;
  const nextCommand = await loadCommandFromUrl(command.queueCommandUrl);
  if (!nextCommand || nextCommand.sceneId === command.sceneId) return null;
  await postEvent(nextCommand, {
    eventType: "queue-advance",
    status: "ready",
    detail: `Loaded next Grok scene ${nextCommand.sceneId} after importing ${command.sceneId}.`,
  });
  return nextCommand;
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

function imagineUrlForCommand(command) {
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

async function ensureGrokTab(command) {
  const grokUrl = imagineUrlForCommand(command);
  const tabs = await chrome.tabs.query({});
  let tab = tabs.find((item) => isImagineTabUrl(item.url));
  if (!tab) {
    tab = await chrome.tabs.create({ url: grokUrl, active: true });
  } else {
    await chrome.tabs.update(tab.id, { active: true });
  }
  await waitForTabComplete(tab.id);
  return chrome.tabs.get(tab.id);
}

async function sendToGrokTab(tab, command, type) {
  return chrome.tabs.sendMessage(tab.id, { type, command });
}

async function sendToGrokTabWithInjection(tab, command, type) {
  try {
    return await sendToGrokTab(tab, command, type);
  } catch (error) {
    if (!isReceivingEndError(error) || !(await injectContentScript(tab))) {
      throw error;
    }
    return sendToGrokTab(tab, command, type);
  }
}

async function sendToGrokTabWithRetry(tab, command, type, attempts = 10) {
  let lastError = "";
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await sendToGrokTabWithInjection(tab, command, type);
    } catch (error) {
      lastError = String(error && error.message ? error.message : error);
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
  return { ok: false, error: lastError || "content-script-not-ready" };
}

async function runAutostartFromTabUrl(tabId, url) {
  const request = autostartRequestFromUrl(url);
  if (!request) return;
  const key = `${tabId}:${request.commandUrl}:${request.action}`;
  if (handledAutostartKeys.has(key)) return;
  handledAutostartKeys.add(key);
  let command = null;
  try {
    let parsedCommandUrl;
    try {
      parsedCommandUrl = new URL(request.commandUrl);
    } catch (error) {
      throw new Error(`invalid autostart command URL: ${request.commandUrl}`);
    }
    // SSRF guard: commandUrl comes from the (untrusted) grok.com page hash and
    // drives postDirectAutostartEvent's POST target *before* the command is loaded.
    // Reject any non-bridge origin up front so no request reaches an attacker host.
    if (!BRIDGE_ALLOWED_ORIGINS.has(parsedCommandUrl.origin)) {
      throw new Error(`refusing autostart from non-bridge origin: ${parsedCommandUrl.origin}`);
    }
    const approvedInUrl = parsedCommandUrl.searchParams.get("operatorApproved") === "true";
    if (!request.operatorApproved || !approvedInUrl) {
      throw new Error("operatorApproved=true is required in the Grok autostart URL.");
    }
    await postDirectAutostartEvent(request, {
      eventType: "background-autostart-detected",
      status: "hash-detected",
      detail: `action=${request.action}; autoGenerate=${request.autoGenerate}`,
      currentUrl: url,
    });
    command = await loadCommandFromUrl(request.commandUrl);
    assertProviderAction(command, request.action);
    await postHeartbeat(command, "Background autostart command loaded.");
    await postEvent(command, {
      eventType: "background-autostart-command-loaded",
      status: "loaded",
      detail: `action=${request.action}; autoGenerate=${request.autoGenerate}`,
      currentUrl: url,
    });
    if (request.action === "download-asset") {
      await downloadAssetFromCurrentTab(command, url);
      return;
    }
    let tab = await waitForTabComplete(tabId);
    if (!tab?.id) throw new Error("Grok tab unavailable after autostart URL load.");
    if (!isImagineTabUrl(tab.url)) {
      await postEvent(command, {
        eventType: "background-autostart-fill",
        status: "failed",
        detail: `imagine-surface-required-background-autostart; active=${tab.url || url}`,
        currentUrl: tab.url || url,
      });
      return;
    }
    const type = request.action === "probe" ? "probe" : "fill-prompt";
    const fillResult = await sendToGrokTabWithRetry(tab, command, type);
    await postEvent(command, {
      eventType: "background-autostart-fill",
      status: fillResult?.ok ? "filled" : "failed",
      detail: fillResult?.label || fillResult?.error || "Prompt fill attempted from background URL watcher.",
      currentUrl: fillResult?.currentUrl || tab.url || url,
    });
    if (!fillResult?.ok || !request.autoGenerate) return;
    await new Promise((resolve) => setTimeout(resolve, 450));
    const generateResult = await sendToGrokTabWithRetry(tab, command, "click-generate", 4);
    await postEvent(command, {
      eventType: "background-autostart-generate",
      status: generateResult?.ok ? "clicked" : "failed",
      detail: generateResult?.label || generateResult?.error || "Generate attempted from background URL watcher.",
      currentUrl: generateResult?.currentUrl || tab.url || url,
    });
  } catch (error) {
    const detail = String(error && error.message ? error.message : error);
    if (command) {
      await postEvent(command, {
        eventType: "background-autostart",
        status: "failed",
        detail,
        currentUrl: url,
      });
    } else {
      await postDirectAutostartEvent(request, {
        eventType: "background-autostart",
        status: "failed",
        detail,
        currentUrl: url,
      });
    }
  }
}

async function prepGenerateNextScene(nextCommand, previousCommand) {
  if (!nextCommand || !(await getAutoQueueEnabled())) return null;
  const tab = await ensureGrokTab(nextCommand);
  await postEvent(nextCommand, {
    eventType: "auto-queue",
    status: "preparing",
    detail: `Auto queue prepping ${nextCommand.sceneId || "next scene"} after ${previousCommand?.sceneId || "previous scene"}.`,
  });
  const fillResult = isImagineTabUrl(tab?.url)
    ? await sendToGrokTab(tab, nextCommand, "fill-prompt")
    : { ok: false, error: "imagine-surface-required-background-autoqueue", currentUrl: tab?.url || "" };
  await postEvent(nextCommand, {
    eventType: "auto-queue-fill",
    status: fillResult?.ok ? "filled" : "failed",
    detail: fillResult?.label || fillResult?.error || "Prompt fill attempted.",
    currentUrl: fillResult?.currentUrl || tab.url || "",
  });
  if (!fillResult?.ok) return { fill: fillResult };
  await new Promise((resolve) => setTimeout(resolve, 450));
  const generateResult = await sendToGrokTab(tab, nextCommand, "click-generate");
  await postEvent(nextCommand, {
    eventType: "auto-queue-generate",
    status: generateResult?.ok ? "clicked" : "failed",
    detail: generateResult?.label || generateResult?.error || "Generate attempted.",
    currentUrl: generateResult?.currentUrl || tab.url || "",
  });
  return { fill: fillResult, generate: generateResult };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (message?.type === "store-command") {
      if (sender?.id !== chrome.runtime.id) {
        sendResponse({ ok: false, error: "store-command sender not allowed" });
        return;
      }
      await setStoredCommand(message.command);
      await setStoredCommandUrl(message.commandUrl || message.command?.commandUrl || "");
      await postHeartbeat(message.command, "Command stored in companion.");
      await postEvent(message.command, {
        eventType: "command-loaded",
        status: "ready",
        detail: "Grok command loaded in Chrome companion."
      });
      sendResponse({ ok: true });
      return;
    }

    if (message?.type === "load-command-url") {
      if (sender?.id !== chrome.runtime.id) {
        sendResponse({ ok: false, error: "load-command-url sender not allowed" });
        return;
      }
      try {
        const loaded = await loadCommandFromUrl(message.commandUrl || "");
        assertProviderAction(loaded, message.action || "fill-prompt");
        sendResponse({ ok: true, command: loaded });
      } catch (error) {
        sendResponse({ ok: false, error: String(error && error.message ? error.message : error) });
      }
      return;
    }

    if (message?.type === "bridge-post-event") {
      if (sender?.id !== chrome.runtime.id) {
        sendResponse({ ok: false, error: "bridge-post-event sender not allowed" });
        return;
      }
      try {
        const result = await postBridgeEvent(message.endpoint || "", message.payload || {});
        sendResponse({ ok: true, result });
      } catch (error) {
        sendResponse({ ok: false, error: String(error && error.message ? error.message : error) });
      }
      return;
    }

    if (message?.type === "content-ready") {
      const command = await getStoredCommand();
      const currentUrl = message.currentUrl || sender?.tab?.url || "";
      if (command) {
        await postHeartbeat(command, "Grok tab content script loaded with stored command.");
        await postEvent(command, {
          eventType: "content-script-ready",
          status: "ready",
          detail: `Grok tab content script loaded; ${extensionBuildDetail()}`,
          currentUrl
        });
      }
      sendResponse({ ok: true, storedCommand: Boolean(command), currentUrl });
      return;
    }

    if (message?.type === "extension-event") {
      const command = message.command || await getStoredCommand();
      await postEvent(command, message.event || {});
      sendResponse({ ok: true });
      return;
    }

    if (message?.type === "download-candidate") {
      const command = message.command || await getStoredCommand();
      const currentUrl = message.currentUrl || sender?.tab?.url || "";
      try {
        const result = await downloadAssetUrl(
          command,
          message.candidateUrl || "",
          currentUrl,
          "background-candidate-download",
          {
            sourceKind: message.sourceKind || "",
            videoWidth: message.videoWidth ?? "",
            videoHeight: message.videoHeight ?? "",
            qualityFloorMet: message.qualityFloorMet ?? "",
            qualityNote: message.qualityNote || "",
          }
        );
        sendResponse({ ok: true, ...result });
      } catch (error) {
        const detail = String(error && error.message ? error.message : error);
        await postEvent(command, {
          eventType: "background-candidate-download",
          status: "failed",
          detail,
          currentUrl,
          candidateUrl: message.candidateUrl || "",
          sourceKind: message.sourceKind || "",
          videoWidth: message.videoWidth ?? "",
          videoHeight: message.videoHeight ?? "",
          qualityFloorMet: message.qualityFloorMet ?? "",
          qualityNote: message.qualityNote || "",
        });
        sendResponse({ ok: false, error: detail });
      }
      return;
    }

    if (message?.type === "direct-import-complete") {
      const command = message.command || await getStoredCommand();
      const currentUrl = message.currentUrl || sender?.tab?.url || "";
      try {
        const imported = message.imported || {};
        const nextCommand = await advanceToNextScene(command, imported);
        let autoQueueResult = null;
        let autoQueueState = "off";
        if (nextCommand && (await getAutoQueueEnabled())) {
          try {
            autoQueueResult = await prepGenerateNextScene(nextCommand, command);
            autoQueueState = autoQueueResult ? "attempted" : "off";
          } catch (error) {
            autoQueueState = "failed";
            await postEvent(nextCommand, {
              eventType: "auto-queue",
              status: "failed",
              detail: String(error && error.message ? error.message : error),
              currentUrl,
              candidateUrl: message.candidateUrl || "",
              sourceKind: message.sourceKind || "",
              videoWidth: message.videoWidth ?? "",
              videoHeight: message.videoHeight ?? "",
              qualityFloorMet: message.qualityFloorMet ?? "",
              qualityNote: message.qualityNote || "",
            });
          }
        }
        sendResponse({
          ok: true,
          nextSceneId: nextCommand?.sceneId || imported.nextMissingSceneId || "",
          autoQueue: autoQueueState,
          autoQueueResult,
        });
      } catch (error) {
        const detail = String(error && error.message ? error.message : error);
        await postEvent(command, {
          eventType: "direct-import-complete",
          status: "failed",
          detail,
          currentUrl,
          candidateUrl: message.candidateUrl || "",
          sourceKind: message.sourceKind || "",
          videoWidth: message.videoWidth ?? "",
          videoHeight: message.videoHeight ?? "",
          qualityFloorMet: message.qualityFloorMet ?? "",
          qualityNote: message.qualityNote || "",
        });
        sendResponse({ ok: false, error: detail });
      }
      return;
    }

    if (message?.type === "set-auto-queue") {
      await setAutoQueueEnabled(message.enabled === true);
      const command = await getStoredCommand();
      await postHeartbeat(command, `Auto queue ${message.enabled === true ? "enabled" : "disabled"}.`);
      sendResponse({ ok: true, enabled: await getAutoQueueEnabled() });
      return;
    }

    if (message?.type === "get-auto-queue") {
      sendResponse({ ok: true, enabled: await getAutoQueueEnabled() });
      return;
    }

    sendResponse({ ok: false, error: "unknown message" });
  })();
  return true;
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  const url = changeInfo.url || tab?.url || "";
  if (url) runAutostartFromTabUrl(tabId, url);
  if (changeInfo.status === "complete" && tab?.url) runAutostartFromTabUrl(tabId, tab.url);
});

chrome.tabs.onCreated.addListener((tab) => {
  if (tab?.id && tab.url) runAutostartFromTabUrl(tab.id, tab.url);
});

chrome.tabs.query({ url: ["https://grok.com/*", "https://*.grok.com/*"] }, (tabs) => {
  for (const tab of tabs || []) {
    if (tab?.id && tab.url) runAutostartFromTabUrl(tab.id, tab.url);
  }
});

chrome.runtime.onInstalled.addListener(() => {
  ensureKeepaliveAlarm();
});

chrome.runtime.onStartup.addListener(() => {
  ensureKeepaliveAlarm();
  postStoredHeartbeat("Companion service worker restarted.");
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm?.name !== KEEPALIVE_ALARM_NAME) return;
  postStoredHeartbeat("Companion keepalive while Grok generation or download is pending.");
});

ensureKeepaliveAlarm();
postStoredHeartbeat("Companion service worker active.");

chrome.downloads.onChanged.addListener((delta) => {
  if (!delta.state || delta.state.current !== "complete") return;
  chrome.downloads.search({ id: delta.id }, async (items) => {
    const item = items && items[0];
    if (!item || !String(item.filename || "").toLowerCase().endsWith(".mp4")) return;
    const command = await getStoredCommand();
    await postEvent(command, {
      eventType: "download-complete",
      status: "downloaded",
      detail: `Chrome download completed: ${item.filename}`,
      candidateUrl: item.url || ""
    });
    try {
      const imported = await importDownloadedMp4(command, item.filename);
      if (imported) {
        const nextCommand = await advanceToNextScene(command, imported);
        let autoQueueResult = null;
        let autoQueueState = "off";
        if (nextCommand) {
          if (await getAutoQueueEnabled()) {
            try {
              autoQueueResult = await prepGenerateNextScene(nextCommand, command);
              autoQueueState = autoQueueResult ? "attempted" : "off";
            } catch (error) {
              autoQueueState = "failed";
              await postEvent(nextCommand, {
                eventType: "auto-queue",
                status: "failed",
                detail: String(error && error.message ? error.message : error),
                candidateUrl: item.url || ""
              });
            }
          }
        }
        await postEvent(command, {
          eventType: "auto-import",
          status: imported.imported?.length ? "imported" : "no-match",
          detail: `readyScenes=${imported.readyScenes || 0}/${imported.totalScenes || 0}; imported=${(imported.imported || []).length}; next=${nextCommand?.sceneId || imported.nextMissingSceneId || ""}; autoQueue=${autoQueueState}`,
          candidateUrl: item.url || ""
        });
      }
    } catch (error) {
      await postEvent(command, {
        eventType: "auto-import",
        status: "failed",
        detail: String(error && error.message ? error.message : error),
        candidateUrl: item.url || ""
      });
    }
  });
});
