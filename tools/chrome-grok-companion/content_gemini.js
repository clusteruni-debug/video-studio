(() => {
  const EXTENSION_BUILD_TAG = "20260607-gemini-image-handoff";
  const BRIDGE_ALLOWED_ORIGIN = "http://127.0.0.1:5161";
  const PROVIDER_CAPABILITIES = Object.freeze({
    "gemini-web-image": Object.freeze({
      canProbe: true,
      canFillPrompt: true,
      canClickGenerate: false,
      canImportResult: false,
      canGenerateVideo: false
    })
  });

  function textOf(element) {
    if (!element) return "";
    return [
      element.innerText,
      element.textContent,
      element.getAttribute?.("aria-label"),
      element.getAttribute?.("title"),
      element.getAttribute?.("placeholder")
    ].filter(Boolean).join(" ").trim();
  }

  function isVisible(element) {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return rect.width > 4 && rect.height > 4 && style.visibility !== "hidden" && style.display !== "none";
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

  function providerCapabilities(provider) {
    return PROVIDER_CAPABILITIES[String(provider || "gemini-web-image")] || null;
  }

  function capabilityForAction(action) {
    if (action === "probe") return "canProbe";
    if (action === "fill-prompt") return "canFillPrompt";
    return "";
  }

  function isGeminiHost(hostname = location.hostname) {
    const value = String(hostname || "").toLowerCase();
    return value === "gemini.google.com" || /^gemini\.google-[a-z0-9-]+\.com$/.test(value);
  }

  function assertProviderAction(command, action) {
    const capabilities = providerCapabilities(command?.provider);
    if (!capabilities) {
      throw new Error(`unsupported Gemini companion provider: ${command?.provider || "unknown"}`);
    }
    const capability = capabilityForAction(action);
    if (!capability || capabilities[capability] !== true) {
      throw new Error("Gemini companion supports fill-prompt/probe only; generate remains operator-owned.");
    }
  }

  function markCompanionLoaded() {
    window.__VIDEO_STUDIO_GEMINI_COMPANION_LOADED__ = {
      loaded: true,
      version: extensionVersion(),
      build: EXTENSION_BUILD_TAG,
      currentUrl: location.href
    };
    document.documentElement.dataset.videoStudioGeminiCompanion = "loaded";
    document.documentElement.dataset.videoStudioGeminiCompanionBuild = EXTENSION_BUILD_TAG;
  }

  function editableCandidates() {
    return Array.from(document.querySelectorAll([
      "textarea",
      "input[type='text']",
      "[contenteditable='true']",
      "[role='textbox']"
    ].join(","))).filter(isVisible);
  }

  function findPromptBox() {
    const candidates = editableCandidates().map((element) => {
      const text = textOf(element).toLowerCase();
      const rect = element.getBoundingClientRect();
      let score = 0;
      if (element.tagName === "TEXTAREA") score += 10;
      if (element.getAttribute("contenteditable") === "true") score += 8;
      if (element.getAttribute("role") === "textbox") score += 7;
      if (/prompt|ask|message|gemini|describe|image|create|generate/.test(text)) score += 8;
      if (/search|filter|settings|history/.test(text)) score -= 10;
      if (rect.width > 260) score += 3;
      if (rect.height > 28) score += 2;
      if (rect.top > window.innerHeight * 0.35) score += 2;
      return { element, score, text };
    }).sort((a, b) => b.score - a.score);
    const best = candidates[0];
    return best && best.score >= 8 ? best.element : null;
  }

  function setPromptValue(element, prompt) {
    element.focus();
    if ("value" in element) {
      element.value = prompt;
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
      return;
    }
    element.textContent = prompt;
    element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: prompt }));
  }

  function autostartRequestFromHash() {
    const rawHash = String(location.hash || "").replace(/^#/, "");
    if (!rawHash) return null;
    const params = new URLSearchParams(rawHash);
    const commandUrl = params.get("videoStudioCommandUrl")
      || params.get("videoStudioGeminiCommandUrl")
      || params.get("vsCommandUrl")
      || "";
    if (!commandUrl) return null;
    return {
      commandUrl,
      provider: params.get("videoStudioProvider") || "gemini-web-image",
      action: params.get("videoStudioAction") || "fill-prompt",
      operatorApproved: params.get("operatorApproved") === "true"
    };
  }

  function autostartEventTarget(request) {
    try {
      const commandUrl = new URL(request.commandUrl);
      if (commandUrl.origin !== BRIDGE_ALLOWED_ORIGIN) return null;
      const parts = commandUrl.pathname.split("/").filter(Boolean);
      const episodeIndex = parts.indexOf("episodes");
      const handoffIndex = parts.indexOf("browser-handoffs");
      const providerIndex = parts.indexOf("gemini-web-image");
      const episodeId = episodeIndex >= 0 ? parts[episodeIndex + 1] : "";
      const batchId = providerIndex >= 0 ? parts[providerIndex + 1] : "";
      if (!episodeId || handoffIndex < 0) return null;
      return {
        endpoint: `${commandUrl.origin}/api/episodes/${encodeURIComponent(episodeId)}/browser-handoffs/extension-event`,
        episodeId,
        batchId,
        cutId: commandUrl.searchParams.get("cutId") || ""
      };
    } catch (error) {
      return null;
    }
  }

  async function postBridgeEvent(endpoint, payload) {
    const result = await chrome.runtime.sendMessage({
      type: "bridge-post-event",
      endpoint,
      payload
    });
    if (!result?.ok) {
      throw new Error(result?.error || "bridge event post failed");
    }
    return result;
  }

  async function reportAutostartRequest(request, event) {
    const target = autostartEventTarget(request);
    if (!target) return;
    await postBridgeEvent(target.endpoint, {
      operatorApproved: true,
      extensionApproved: true,
      provider: request.provider || "gemini-web-image",
      episodeId: target.episodeId,
      batchId: target.batchId,
      cutId: target.cutId,
      currentUrl: event.currentUrl || location.href,
      build: EXTENSION_BUILD_TAG,
      eventType: event.eventType || "gemini-extension-event",
      status: event.status || "reported",
      detail: event.detail || ""
    }).catch((error) => console.warn("Video Studio Gemini direct autostart event failed", error));
  }

  async function report(command, event) {
    if (!command?.eventEndpoint) return;
    await postBridgeEvent(command.eventEndpoint, {
      operatorApproved: true,
      extensionApproved: true,
      provider: command.provider || "gemini-web-image",
      episodeId: command.episodeId || "",
      batchId: command.batchId || "",
      cutId: command.cutId || "",
      sceneId: command.sceneId || "",
      expectedFileName: command.expectedFileName || "",
      currentUrl: event.currentUrl || location.href,
      build: EXTENSION_BUILD_TAG,
      eventType: event.eventType || "gemini-extension-event",
      status: event.status || "reported",
      detail: event.detail || ""
    }).catch((error) => console.warn("Video Studio Gemini companion event failed", error));
  }

  async function loadAutostartCommand(request) {
    if (!request.operatorApproved || !request.commandUrl.includes("operatorApproved=true")) {
      throw new Error("operatorApproved=true is required in the Gemini autostart URL.");
    }
    let parsedCommandUrl;
    try {
      parsedCommandUrl = new URL(request.commandUrl);
    } catch (error) {
      throw new Error(`invalid Gemini command URL: ${request.commandUrl}`);
    }
    if (parsedCommandUrl.origin !== BRIDGE_ALLOWED_ORIGIN) {
      throw new Error(`refusing Gemini command from non-bridge origin: ${parsedCommandUrl.origin}`);
    }
    const loaded = await chrome.runtime.sendMessage({
      type: "load-command-url",
      commandUrl: request.commandUrl,
      action: request.action
    });
    if (!loaded?.ok || !loaded.command || loaded.command.ok === false) {
      throw new Error(loaded?.error || loaded?.command?.error || "command load failed");
    }
    const command = loaded.command;
    assertProviderAction(command, request.action);
    command.commandUrl = request.commandUrl;
    return command;
  }

  async function fillPrompt(command) {
    if (!isGeminiHost()) {
      await report(command, {
        eventType: "gemini-surface-check",
        status: "failed",
        detail: `gemini-surface-required; ${extensionBuildDetail()}`,
        currentUrl: location.href
      });
      return { ok: false, error: "gemini-surface-required", currentUrl: location.href };
    }
    if (providerCapabilities(command?.provider)?.canFillPrompt !== true) {
      return { ok: false, error: "gemini-fill-not-supported-for-provider", currentUrl: location.href };
    }
    const editableCount = editableCandidates().length;
    const box = findPromptBox();
    if (!box) {
      await report(command, {
        eventType: "gemini-prompt-target-missing",
        status: "failed",
        detail: `editable=${editableCount}; ${extensionBuildDetail()}`,
        currentUrl: location.href
      });
      return { ok: false, error: "gemini-prompt-input-not-found", currentUrl: location.href, editableCount };
    }
    await report(command, {
      eventType: "gemini-prompt-target-found",
      status: "ready",
      detail: `editable=${editableCount}; tag=${box.tagName.toLowerCase()}; ${extensionBuildDetail()}`,
      currentUrl: location.href
    });
    setPromptValue(box, command.prompt || "");
    return { ok: true, currentUrl: location.href, filledLength: String(command.prompt || "").length };
  }

  async function runAutostart() {
    const request = autostartRequestFromHash();
    if (!request) return;
    const runKey = `videoStudioGeminiAutostart:${request.commandUrl}:${request.action}`;
    if (window.sessionStorage.getItem(runKey)) return;
    window.sessionStorage.setItem(runKey, "started");
    let command = null;
    try {
      await reportAutostartRequest(request, {
        eventType: "gemini-content-ready",
        status: "hash-detected",
        detail: `${extensionBuildDetail()}; action=${request.action}`,
        currentUrl: location.href
      });
      command = await loadAutostartCommand(request);
      await report(command, {
        eventType: "gemini-command-loaded",
        status: "loaded",
        detail: `${extensionBuildDetail()}; action=${request.action}`
      });
      if (request.action === "probe") {
        await report(command, {
          eventType: "gemini-probe",
          status: "ready",
          detail: `editable=${editableCandidates().length}; capabilities=probe,fill-prompt; generate=false; import=false; ${extensionBuildDetail()}`
        });
        return;
      }
      const result = await fillPrompt(command);
      await report(command, {
        eventType: "gemini-prompt-fill",
        status: result.ok ? "filled" : "failed",
        detail: result.ok
          ? `filledLength=${result.filledLength}; generate remains operator-owned; ${extensionBuildDetail()}`
          : `${result.error || "prompt fill failed"}; ${extensionBuildDetail()}`,
        currentUrl: result.currentUrl
      });
    } catch (error) {
      if (!command) {
        await reportAutostartRequest(request, {
          eventType: "gemini-command-load-failed",
          status: "failed",
          detail: String(error && error.message ? error.message : error),
          currentUrl: location.href
        });
      }
      await report(command, {
        eventType: "gemini-autostart",
        status: "failed",
        detail: String(error && error.message ? error.message : error)
      });
      console.warn("Video Studio Gemini companion autostart failed", error);
    }
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    (async () => {
      if (message?.type === "fill-prompt") {
        const result = await fillPrompt(message.command || {});
        sendResponse(result);
        return;
      }
      if (message?.type === "probe") {
        sendResponse({
          ok: true,
          provider: "gemini-web-image",
          capabilities: providerCapabilities("gemini-web-image"),
          editableCount: editableCandidates().length,
          currentUrl: location.href
        });
        return;
      }
      sendResponse({ ok: false, error: "unknown message" });
    })();
    return true;
  });

  markCompanionLoaded();
  runAutostart();
})();
