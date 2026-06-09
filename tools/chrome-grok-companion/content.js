(() => {
  const EXTENSION_BUILD_TAG = "20260607-popup-state-fix";
  const PROVIDER_CAPABILITIES = Object.freeze({
    "grok-web-video": Object.freeze({
      canProbe: true,
      canFillPrompt: true,
      canClickGenerate: true,
      canImportResult: true,
      canGenerateVideo: true
    })
  });

  function isVisible(element) {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return rect.width > 4 && rect.height > 4 && style.visibility !== "hidden" && style.display !== "none";
  }

  function textOf(element) {
    return [
      element.innerText,
      element.textContent,
      element.getAttribute("aria-label"),
      element.getAttribute("title"),
      element.getAttribute("placeholder")
    ].filter(Boolean).join(" ").trim();
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
      throw new Error(`unsupported Grok companion provider: ${commandProvider(command)}`);
    }
    const capability = capabilityForAction(action);
    if (!capability || capabilities[capability] !== true) {
      throw new Error(`Grok companion action not supported for provider=${commandProvider(command)} action=${action}`);
    }
  }

  function editableCandidates() {
    const selectors = [
      "textarea",
      "input[type='text']",
      "input:not([type])",
      "[contenteditable='true']",
      "[role='textbox']",
      ".ProseMirror",
      "div[contenteditable]"
    ];
    const nodes = selectors.flatMap((selector) => Array.from(document.querySelectorAll(selector)));
    return nodes.filter((node, index, all) => {
      if (all.indexOf(node) !== index || !isVisible(node)) return false;
      if (node.disabled || node.readOnly || node.getAttribute("aria-disabled") === "true") return false;
      return true;
    });
  }

  function centerOf(element) {
    const rect = element.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, rect };
  }

  function proximityScore(element, reference) {
    if (!element || !reference) return 0;
    const a = centerOf(element);
    const b = centerOf(reference);
    const distance = Math.hypot(a.x - b.x, a.y - b.y);
    return Math.max(0, 18 - Math.min(18, distance / 45));
  }

  function chatComposerTextPattern() {
    return /ask|message|chat|send|submit|grok|anything|무엇이든|물어|메시지|채팅|대화|보내기|전송|제출/i;
  }

  function imaginePromptTextPattern() {
    return /prompt|describe|imagine|video|create|generate|make|animate|motion|프롬프트|설명|상상|동영상|영상|생성|만들|애니/i;
  }

  function promptBoxAssessment(element) {
    const text = textOf(element);
    const rect = element.getBoundingClientRect();
    const positive = imaginePromptTextPattern().test(text);
    const chatLike = chatComposerTextPattern().test(text);
    const formText = textOf(element.closest?.("form") || element.parentElement || element);
    const formChatLike = chatComposerTextPattern().test(formText) && !imaginePromptTextPattern().test(formText);
    return {
      text,
      positive,
      chatLike,
      formChatLike,
      lowerComposer: rect.top > window.innerHeight * 0.55 && !positive,
      status: (chatLike || formChatLike) && !positive ? "chat-composer" : "candidate"
    };
  }

  function setPromptValue(element, prompt) {
    element.focus();
    if ("value" in element) {
      const prototype = Object.getPrototypeOf(element);
      const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
      if (descriptor && descriptor.set) {
        descriptor.set.call(element, prompt);
      } else {
        element.value = prompt;
      }
    } else {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(element);
      selection.removeAllRanges();
      selection.addRange(range);
      const inserted = document.execCommand && document.execCommand("insertText", false, prompt);
      if (!inserted || !String(element.textContent || "").includes(prompt.slice(0, 24))) {
        element.textContent = prompt;
      }
      selection.removeAllRanges();
    }
    element.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: " " }));
    element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: prompt }));
    element.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, key: " " }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function findPromptBox() {
    const boxes = editableCandidates();
    const ranked = boxes.map((box) => {
      const assessment = promptBoxAssessment(box);
      const text = assessment.text.toLowerCase();
      const rect = box.getBoundingClientRect();
      let score = 0;
      if (box.tagName === "TEXTAREA") score += 10;
      if (box.tagName === "INPUT") score += 4;
      if (box.getAttribute("contenteditable") === "true") score += 6;
      if (box.getAttribute("role") === "textbox") score += 6;
      if (assessment.positive) score += 12;
      if (text.includes("prompt") || text.includes("describe") || text.includes("imagine")) score += 8;
      if (text.includes("설명") || text.includes("프롬프트") || text.includes("동영상") || text.includes("영상")) score += 8;
      if (assessment.chatLike) score -= 18;
      if (assessment.formChatLike) score -= 18;
      if (assessment.lowerComposer) score -= 10;
      if (rect.width > 280) score += 3;
      if (rect.height > 32) score += 2;
      if (rect.top > window.innerHeight * 0.35) score += 2;
      return { box, score, assessment };
    }).sort((a, b) => b.score - a.score);
    const best = ranked[0];
    if (!best || best.score < 8) return null;
    if (best.assessment.status === "chat-composer") return null;
    return best.box || null;
  }

  function buttonCandidates(words, referenceBox = null, options = {}) {
    const controls = Array.from(document.querySelectorAll("button, [role='button'], a, input[type='button'], input[type='submit']"));
    const referenceForm = referenceBox?.closest?.("form") || null;
    return controls
      .filter((element) => isVisible(element) && !element.disabled && element.getAttribute("aria-disabled") !== "true")
      .map((element) => {
        const text = textOf(element).toLowerCase();
        const wordScore = words.reduce((total, word) => total + (text.includes(word) ? 10 : 0), 0);
        let score = wordScore;
        if (element.tagName === "INPUT" && element.type === "submit") score += 8;
        if (referenceForm && element.closest("form") === referenceForm) score += 12;
        if (referenceBox) score += proximityScore(element, referenceBox);
        if (options.allowIconButtons && !text && element.querySelector("svg")) score += 5;
        if (options.preferRightOfReference && referenceBox) {
          const control = centerOf(element).rect;
          const reference = centerOf(referenceBox).rect;
          if (control.left >= reference.left && control.top >= reference.top - 80) score += 4;
        }
        if (options.requireWordMatch && wordScore <= 0) score = -100;
        return { element, text, score, wordScore };
      })
      .filter((item) => item.score > (options.minimumScore || 0))
      .sort((a, b) => b.score - a.score);
  }

  function activeVideoModeControl() {
    const controls = Array.from(document.querySelectorAll("button, [role='button'], [role='tab'], a"));
    return controls
      .filter((element) => isVisible(element))
      .find((element) => {
        const text = textOf(element).toLowerCase();
        const selected = element.getAttribute("aria-pressed") === "true"
          || element.getAttribute("aria-selected") === "true"
          || element.classList.contains("active")
          || Boolean(element.closest("[aria-selected='true'], [aria-pressed='true'], .active"));
        return selected && /video|animate|motion|movie|clip|동영상|영상|애니/.test(text);
      });
  }

  function imagineSurfaceStatus() {
    const pathname = String(location.pathname || "").toLowerCase();
    if (pathname.startsWith("/c/")) {
      return { ok: false, status: "general-chat-thread", error: "imagine-surface-required-general-chat-thread" };
    }
    if (pathname.startsWith("/imagine/post")) {
      return { ok: false, status: "imagine-post", error: "imagine-composer-required-not-post" };
    }
    if (!pathname.startsWith("/imagine")) {
      return { ok: false, status: "not-imagine", error: "imagine-surface-required" };
    }
    return { ok: true, status: "imagine" };
  }

  async function ensureVideoMode() {
    const surface = imagineSurfaceStatus();
    if (!surface.ok) {
      return { ok: false, ...surface, label: "Open Grok Imagine before filling or generating video." };
    }
    const active = activeVideoModeControl();
    if (active) {
      return { ok: true, status: "already-video", label: textOf(active) || "video" };
    }
    const words = ["video", "videos", "animate", "motion", "movie", "clip", "동영상", "영상", "애니메이션"];
    const candidate = buttonCandidates(words, null, { allowIconButtons: true, minimumScore: 9 })[0];
    if (!candidate) {
      return { ok: false, status: "video-mode-not-found", error: "video-mode-control-not-found" };
    }
    candidate.element.click();
    await new Promise((resolve) => setTimeout(resolve, 650));
    const selected = activeVideoModeControl();
    if (!selected) {
      return { ok: false, status: "video-mode-not-confirmed", error: "video-mode-control-not-confirmed", label: candidate.text || "video mode", score: candidate.score };
    }
    return { ok: true, status: "clicked", label: textOf(selected) || candidate.text || "video mode", score: candidate.score };
  }

  function mp4AssetCandidateFromUrl(url) {
    const value = String(url || "");
    const cleanUrl = value.split("#")[0];
    const pathname = cleanUrl.split("?")[0].toLowerCase();
    if (!pathname.endsWith(".mp4")) return null;
    return {
      url: cleanUrl,
      kind: "url",
      label: "current MP4 asset tab",
      sourceKind: "direct-mp4-asset-tab",
      qualityFloorMet: null,
      qualityNote: "original-download-source"
    };
  }

  function qualityMetaForVisibleVideo(video, url) {
    const videoWidth = Number(video?.videoWidth || video?.getAttribute?.("width") || 0) || 0;
    const videoHeight = Number(video?.videoHeight || video?.getAttribute?.("height") || 0) || 0;
    const qualityFloorMet = videoWidth >= 720 && videoHeight >= 1280;
    return {
      url,
      kind: String(url).startsWith("blob:") ? "blob" : "url",
      label: qualityFloorMet ? "visible video fallback" : "visible video fallback proof-only",
      sourceKind: "visible-video-fallback",
      videoWidth,
      videoHeight,
      qualityFloorMet,
      qualityNote: qualityFloorMet
        ? `visible-video-floor-met:${videoWidth}x${videoHeight}`
        : `visible-video-below-floor:${videoWidth}x${videoHeight}`
    };
  }

  function directImportableMp4VideoCandidate(candidate) {
    if (!candidate || candidate.kind !== "url" || !candidate.url) return null;
    const asset = mp4AssetCandidateFromUrl(candidate.url);
    if (!asset) return null;
    if (candidate.sourceKind === "visible-video-fallback" && candidate.qualityFloorMet !== true) {
      return null;
    }
    const qualityTags = [
      candidate.qualityNote || "visible-video-floor-met",
      "original-download-source",
      "companion-direct-fetch",
      "no-browser-download-prompt"
    ];
    return {
      ...candidate,
      url: asset.url,
      label: "visible Grok MP4 direct import",
      sourceKind: "companion-direct-fetch",
      qualityNote: qualityTags.filter(Boolean).join("; ")
    };
  }

  function collectVideoCandidates() {
    const candidates = Array.from(document.querySelectorAll("video"))
      .filter(isVisible)
      .map((video) => ({ video, url: video.currentSrc || video.src }))
      .filter((item) => item.url)
      .map((item) => qualityMetaForVisibleVideo(item.video, item.url));
    const directAsset = mp4AssetCandidateFromUrl(location.href);
    if (directAsset && !candidates.some((item) => item.url === directAsset.url)) {
      candidates.unshift(directAsset);
    }
    return candidates;
  }

  function safeMp4Filename(value) {
    const basename = String(value || "grok-video.mp4")
      .split(/[\\/]/)
      .pop()
      .replace(/[^a-zA-Z0-9._ -]+/g, "-")
      .trim() || "grok-video.mp4";
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

  async function importBlobCandidate(command, candidate, currentUrl) {
    if (!command?.uploadEndpoint) {
      throw new Error("blob direct import requires uploadEndpoint.");
    }
    if (!command?.sceneId) {
      throw new Error("sceneId is required before blob direct import.");
    }
    if (!candidate?.url || candidate.kind !== "blob") {
      throw new Error("blob direct import requires a visible blob video candidate.");
    }
    if (candidate.qualityFloorMet === false) {
      throw new Error("visible-video-fallback-below-quality-floor");
    }
    const response = await fetch(candidate.url, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`blob video fetch failed: HTTP ${response.status}`);
    }
    const buffer = await response.arrayBuffer();
    if (!buffer.byteLength) {
      throw new Error("blob video fetch returned an empty file.");
    }
    const filename = safeMp4Filename(command.expectedFileName || "grok-video.mp4");
    const sourceKind = "visible-video-blob-direct-fetch";
    const qualityNote = `${candidate.qualityNote || "visible-video-floor-met"}; companion-blob-direct-fetch; no-browser-download-prompt`;
    const uploadResponse = await fetch(command.uploadEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operatorApproved: true,
        extensionApproved: true,
        directImportProof: true,
        eventType: "companion-blob-direct-import",
        sceneId: command.sceneId,
        expectedFileName: command.expectedFileName || filename,
        fileName: filename,
        fileBase64: arrayBufferToBase64(buffer),
        currentUrl,
        candidateUrl: candidate.url,
        sourceKind,
        videoWidth: candidate.videoWidth ?? "",
        videoHeight: candidate.videoHeight ?? "",
        qualityFloorMet: candidate.qualityFloorMet ?? "",
        qualityNote,
        detail: `content blob direct bridge import; bytes=${buffer.byteLength}`,
        overwrite: false,
        preserveCandidates: true
      })
    });
    const imported = await uploadResponse.json().catch(() => ({}));
    if (!uploadResponse.ok || imported.ok === false) {
      throw new Error(imported.error || `blob direct import failed: HTTP ${uploadResponse.status}`);
    }
    await report(command, {
      eventType: "companion-blob-direct-import",
      status: (imported.imported || []).length ? "imported" : "no-match",
      detail: `content blob direct bridge import; bytes=${buffer.byteLength}; imported=${(imported.imported || []).length}`,
      currentUrl,
      candidateUrl: candidate.url,
      sourceKind,
      videoWidth: candidate.videoWidth ?? "",
      videoHeight: candidate.videoHeight ?? "",
      qualityFloorMet: candidate.qualityFloorMet ?? "",
      qualityNote
    });
    const queueResult = await chrome.runtime.sendMessage({
      type: "direct-import-complete",
      command,
      imported,
      currentUrl,
      candidateUrl: candidate.url,
      sourceKind,
      videoWidth: candidate.videoWidth ?? "",
      videoHeight: candidate.videoHeight ?? "",
      qualityFloorMet: candidate.qualityFloorMet ?? "",
      qualityNote
    }).catch((error) => ({ ok: false, error: String(error && error.message ? error.message : error) }));
    return {
      ok: true,
      currentUrl,
      directImport: true,
      directImportKind: "content-blob-upload",
      downloadClicked: false,
      candidateUrl: candidate.url,
      filename,
      imported,
      nextSceneId: queueResult?.nextSceneId || imported.nextMissingSceneId || "",
      autoQueue: queueResult?.autoQueue || "off",
      autoQueueResult: queueResult?.autoQueueResult || null,
      queueError: queueResult?.ok === false ? queueResult.error || "queue advance failed" : "",
      videoCandidates: [candidate]
    };
  }

  async function fillPrompt(command) {
    if (providerCapabilities(command)?.canFillPrompt !== true) {
      return { ok: false, error: "grok-fill-not-supported-for-provider", currentUrl: location.href };
    }
    const mode = await ensureVideoMode();
    if (!mode.ok) {
      return {
        ok: false,
        error: mode.error || "imagine-video-mode-required",
        currentUrl: location.href,
        editableCount: editableCandidates().length,
        targetFound: false,
        mode
      };
    }
    const editableCount = editableCandidates().length;
    const box = findPromptBox();
    if (!box) {
      return {
        ok: false,
        error: "prompt-input-not-found",
        currentUrl: location.href,
        editableCount,
        targetFound: false,
        mode
      };
    }
    setPromptValue(box, command.prompt || "");
    return {
      ok: true,
      currentUrl: location.href,
      filledLength: String(command.prompt || "").length,
      editableCount,
      targetFound: true,
      targetTag: box.tagName.toLowerCase(),
      mode
    };
  }

  async function clickGenerate() {
    if (providerCapabilities({ provider: "grok-web-video" })?.canClickGenerate !== true) {
      return { ok: false, error: "grok-generate-not-supported-for-provider", currentUrl: location.href };
    }
    const mode = await ensureVideoMode();
    if (!mode.ok) {
      return { ok: false, error: mode.error || "imagine-video-mode-required", currentUrl: location.href, mode };
    }
    const box = findPromptBox();
    if (!box) {
      return { ok: false, error: "imagine-prompt-input-not-found-or-chat-composer", currentUrl: location.href, mode };
    }
    const words = ["generate", "create", "imagine", "video", "동영상", "영상 생성", "생성", "만들기"];
    const button = buttonCandidates(words, box, {
      allowIconButtons: false,
      preferRightOfReference: true,
      requireWordMatch: true,
      minimumScore: box ? 10 : 0
    })[0];
    if (!button) return { ok: false, error: "generate-button-not-found", currentUrl: location.href, mode };
    button.element.click();
    return { ok: true, currentUrl: location.href, label: button.text || "generate", score: button.score, mode };
  }

  async function clickDownload(command = {}) {
    const currentAsset = mp4AssetCandidateFromUrl(location.href);
    if (currentAsset) {
      return {
        ok: true,
        currentUrl: location.href,
        downloadClicked: false,
        videoCandidates: [currentAsset],
        downloadKind: "direct-mp4-asset-tab"
      };
    }
    const directAnchor = Array.from(document.querySelectorAll("a[download], a[href*='.mp4'], a[href*='video']"))
      .filter(isVisible)
      .map((anchor) => ({
        url: anchor.href,
        kind: "url",
        label: textOf(anchor) || "direct video link",
        sourceKind: anchor.hasAttribute("download") ? "download-anchor" : "direct-video-anchor",
        qualityFloorMet: null,
        qualityNote: "original-download-source"
      }))
      .find((item) => item.url);
    if (directAnchor) {
      if (!command?.uploadEndpoint) {
        return {
          ok: true,
          currentUrl: location.href,
          downloadClicked: false,
          directImportOnly: true,
          videoCandidates: [directAnchor],
          error: "uploadEndpoint-required-no-browser-download-fallback"
        };
      }
      return {
        ok: true,
        currentUrl: location.href,
        downloadClicked: false,
        videoCandidates: [directAnchor]
      };
    }
    const videos = collectVideoCandidates();
    if (command?.uploadEndpoint) {
      const mp4Video = videos.map(directImportableMp4VideoCandidate).find(Boolean);
      if (mp4Video) {
        return {
          ok: true,
          currentUrl: location.href,
          downloadClicked: false,
          videoCandidates: [mp4Video],
          directImportCandidate: true
        };
      }
      const blobVideo = videos.find((item) => item.kind === "blob" && item.qualityFloorMet !== false);
      if (blobVideo) {
        return importBlobCandidate(command, blobVideo, location.href);
      }
      return {
        ok: videos.length > 0,
        currentUrl: location.href,
        downloadClicked: false,
        directImportOnly: true,
        videoCandidates: videos,
        error: videos.length
          ? "direct-import-url-not-found"
          : "direct-import-candidate-not-found"
      };
    }
    return {
      ok: videos.length > 0,
      currentUrl: location.href,
      downloadClicked: false,
      directImportOnly: true,
      videoCandidates: videos,
      error: videos.some((item) => item.sourceKind === "visible-video-fallback" && item.qualityFloorMet === false)
        ? "visible-video-fallback-below-quality-floor"
        : (videos.length ? "uploadEndpoint-required-no-browser-download-fallback" : "direct-import-candidate-not-found")
    };
  }

  function autostartRequestFromHash() {
    const rawHash = String(location.hash || "").replace(/^#/, "");
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
      retries: Math.max(1, Math.min(12, Number(params.get("videoStudioRetries") || 6))),
      retryDelayMs: Math.max(250, Math.min(5000, Number(params.get("videoStudioRetryDelayMs") || 1500)))
    };
  }

  async function report(command, event) {
    if (!command) return;
    try {
      await chrome.runtime.sendMessage({ type: "extension-event", command, event });
    } catch (error) {
      console.warn("Video Studio Grok companion report failed", error);
    }
  }

  function autostartEventTarget(request) {
    try {
      const commandUrl = new URL(request.commandUrl);
      const parts = commandUrl.pathname.split("/").filter(Boolean);
      const handoffIndex = parts.indexOf("grok-handoff");
      const projectId = handoffIndex >= 0 ? parts[handoffIndex + 1] : "";
      if (!projectId) return null;
      return {
        endpoint: `${commandUrl.origin}/api/grok-handoff/${encodeURIComponent(projectId)}/extension-event`,
        sceneId: commandUrl.searchParams.get("sceneId") || ""
      };
    } catch (error) {
      return null;
    }
  }

  async function reportAutostartRequest(request, event) {
    const target = autostartEventTarget(request);
    if (!target) return;
    try {
      await fetch(target.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operatorApproved: true,
          extensionApproved: true,
          source: "chrome-companion",
          sceneId: target.sceneId,
          ...event
        })
      });
    } catch (error) {
      console.warn("Video Studio Grok companion direct autostart report failed", error);
    }
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

  function markCompanionLoaded() {
    try {
      const version = extensionVersion();
      window.__VIDEO_STUDIO_GROK_COMPANION_LOADED__ = {
        loaded: true,
        version,
        currentUrl: location.href
      };
      document.documentElement.dataset.videoStudioGrokCompanion = "loaded";
      document.documentElement.dataset.videoStudioGrokCompanionVersion = version;
    } catch (error) {
      console.warn("Video Studio Grok companion load marker failed", error);
    }
  }

  async function announceContentReady() {
    try {
      await chrome.runtime.sendMessage({
        type: "content-ready",
        currentUrl: location.href,
        version: extensionVersion()
      });
    } catch (error) {
      console.warn("Video Studio Grok companion ready report failed", error);
    }
  }

  async function loadAutostartCommand(request) {
    const response = await fetch(request.commandUrl);
    const command = await response.json().catch(() => ({}));
    if (!response.ok || command.ok === false) {
      throw new Error(command.error || `command load failed: HTTP ${response.status}`);
    }
    command.commandUrl = request.commandUrl;
    await chrome.runtime.sendMessage({ type: "store-command", command, commandUrl: request.commandUrl });
    return command;
  }

  async function attemptPromptFill(command, request) {
    let lastResult = null;
    for (let attempt = 1; attempt <= request.retries; attempt += 1) {
      lastResult = await fillPrompt(command);
      await report(command, {
        eventType: lastResult?.targetFound ? "grok-prompt-target-found" : "grok-prompt-target-missing",
        status: lastResult?.targetFound ? "ready" : "failed",
        detail: `attempt=${attempt}/${request.retries}; editable=${lastResult?.editableCount ?? 0}; tag=${lastResult?.targetTag || ""}; ${lastResult?.error || ""}; ${extensionBuildDetail()}`,
        currentUrl: lastResult?.currentUrl || location.href
      });
      await report(command, {
        eventType: "autostart-fill",
        status: lastResult?.ok ? "filled" : "retry",
        detail: `attempt=${attempt}/${request.retries}; ${lastResult?.label || lastResult?.error || "prompt fill attempted"}`,
        currentUrl: lastResult?.currentUrl || location.href
      });
      if (lastResult?.ok) return lastResult;
      await new Promise((resolve) => setTimeout(resolve, request.retryDelayMs));
    }
    return lastResult;
  }

  function isVisibleVideoDownloadAction(action) {
    return ["download-visible-video", "download-post-video", "download-current-video"].includes(action);
  }

  async function runVisibleVideoDownload(command) {
    const result = await clickDownload(command);
    if (result?.directImport) {
      await report(command, {
        eventType: "autostart-download",
        status: "direct-imported",
        detail: `${result.directImportKind || "companion-direct-import"}; next=${result.nextSceneId || ""}; autoQueue=${result.autoQueue || "off"}; ${result.queueError || ""}`,
        currentUrl: result.currentUrl || location.href,
        candidateUrl: result.candidateUrl || result.videoCandidates?.[0]?.url || "",
        sourceKind: "visible-video-blob-direct-fetch",
        videoWidth: result.videoCandidates?.[0]?.videoWidth ?? "",
        videoHeight: result.videoCandidates?.[0]?.videoHeight ?? "",
        qualityFloorMet: result.videoCandidates?.[0]?.qualityFloorMet ?? "",
        qualityNote: result.videoCandidates?.[0]?.qualityNote
          ? `${result.videoCandidates[0].qualityNote}; companion-blob-direct-fetch; no-browser-download-prompt`
          : "companion-blob-direct-fetch; no-browser-download-prompt"
      });
      return result;
    }
    if (result?.downloadClicked) {
      await report(command, {
        eventType: "autostart-download",
        status: "clicked",
        detail: result.downloadKind || result.label || "download control clicked",
        currentUrl: result.currentUrl || location.href,
        candidateUrl: result.videoCandidates?.[0]?.url || "",
        sourceKind: result.sourceKind || result.videoCandidates?.[0]?.sourceKind || "",
        videoWidth: result.videoWidth ?? result.videoCandidates?.[0]?.videoWidth ?? "",
        videoHeight: result.videoHeight ?? result.videoCandidates?.[0]?.videoHeight ?? "",
        qualityFloorMet: result.qualityFloorMet ?? result.videoCandidates?.[0]?.qualityFloorMet ?? "",
        qualityNote: result.qualityNote || result.videoCandidates?.[0]?.qualityNote || ""
      });
      return result;
    }

    const candidates = Array.isArray(result?.videoCandidates) ? result.videoCandidates : [];
    const urlCandidate = candidates.find((item) => item?.kind === "url" && item?.url);
    const lowQualityVisibleCandidate = candidates.find((item) => (
      item?.sourceKind === "visible-video-fallback" && item?.qualityFloorMet === false
    ));
    if (lowQualityVisibleCandidate) {
      await report(command, {
        eventType: "autostart-download",
        status: "blocked",
        detail: "visible-video-fallback-proof-only; use operator-owned download/import or manual upload for original MP4",
        currentUrl: result?.currentUrl || location.href,
        candidateUrl: lowQualityVisibleCandidate.url || "",
        sourceKind: lowQualityVisibleCandidate.sourceKind || "",
        videoWidth: lowQualityVisibleCandidate.videoWidth ?? "",
        videoHeight: lowQualityVisibleCandidate.videoHeight ?? "",
        qualityFloorMet: false,
        qualityNote: lowQualityVisibleCandidate.qualityNote || "visible-video-below-floor"
      });
      throw new Error("visible-video-fallback-below-quality-floor");
    }
    if (!urlCandidate) {
      throw new Error(result?.error || "download-control-or-mp4-candidate-not-found");
    }

    const downloadResult = await chrome.runtime.sendMessage({
      type: "download-candidate",
      command,
      candidateUrl: urlCandidate.url,
      currentUrl: result.currentUrl || location.href,
      sourceKind: urlCandidate.sourceKind || "",
      videoWidth: urlCandidate.videoWidth ?? "",
      videoHeight: urlCandidate.videoHeight ?? "",
      qualityFloorMet: urlCandidate.qualityFloorMet ?? "",
      qualityNote: urlCandidate.qualityNote || ""
    });
    const fallbackDetail = downloadResult?.error
      || (downloadResult?.blocked ? "native browser download fallback disabled" : "direct import failed");
    await report(command, {
      eventType: "autostart-download",
      status: downloadResult?.directImport ? "direct-imported" : "blocked",
      detail: downloadResult?.directImport
        ? `companion direct import; next=${downloadResult.nextSceneId || ""}; autoQueue=${downloadResult.autoQueue || "off"}`
        : fallbackDetail,
      currentUrl: result.currentUrl || location.href,
      candidateUrl: urlCandidate.url,
      sourceKind: urlCandidate.sourceKind || "",
      videoWidth: urlCandidate.videoWidth ?? "",
      videoHeight: urlCandidate.videoHeight ?? "",
      qualityFloorMet: urlCandidate.qualityFloorMet ?? "",
      qualityNote: urlCandidate.qualityNote || ""
    });
    if (!downloadResult?.directImport) {
      throw new Error(fallbackDetail);
    }
    return { ...result, directImport: downloadResult.directImport === true, backgroundDownload: downloadResult };
  }

  async function runAutostart() {
    const request = autostartRequestFromHash();
    if (!request) return;
    const runKey = `videoStudioGrokAutostart:${request.commandUrl}:${request.action}`;
    if (window.sessionStorage.getItem(runKey)) return;
    window.sessionStorage.setItem(runKey, "started");
    let command = null;
    try {
      if (!request.operatorApproved || !request.commandUrl.includes("operatorApproved=true")) {
        throw new Error("operatorApproved=true is required in the Grok autostart URL.");
      }
      await reportAutostartRequest(request, {
        eventType: "content-script-ready",
        status: "hash-detected",
        detail: `${extensionBuildDetail()}; action=${request.action}; autoGenerate=${request.autoGenerate}`,
        currentUrl: location.href
      });
      command = await loadAutostartCommand(request);
      assertProviderAction(command, request.action);
      await report(command, {
        eventType: "content-script-command-loaded",
        status: "loaded",
        detail: `${extensionBuildDetail()}; action=${request.action}; autoGenerate=${request.autoGenerate}`,
        currentUrl: location.href
      });
      await report(command, {
        eventType: "autostart-command",
        status: "loaded",
        detail: `action=${request.action}; autoGenerate=${request.autoGenerate}`,
        currentUrl: location.href
      });
      if (request.action === "download-asset") {
        const currentAsset = mp4AssetCandidateFromUrl(location.href);
        if (!currentAsset) {
          throw new Error("download-asset action requires the current tab URL to be a direct .mp4 asset.");
        }
        if (!command.uploadEndpoint) {
          await report(command, {
            eventType: "autostart-download",
            status: "blocked",
            detail: "download-asset requires local uploadEndpoint; native browser download fallback disabled",
            currentUrl: location.href,
            candidateUrl: currentAsset.url,
            sourceKind: "direct-mp4-asset-tab",
            qualityNote: "no-browser-download-prompt"
          });
          throw new Error("download-asset direct import requires uploadEndpoint; native browser download fallback disabled.");
        }
        await runVisibleVideoDownload(command);
        return;
      }
      if (isVisibleVideoDownloadAction(request.action)) {
        await runVisibleVideoDownload(command);
        return;
      }
      if (request.action === "probe") {
        const mode = activeVideoModeControl();
        await report(command, {
          eventType: "autostart-probe",
          status: "ready",
          detail: `editable=${editableCandidates().length}; videos=${collectVideoCandidates().length}; activeVideoMode=${Boolean(mode)}; capabilities=probe,fill-prompt,generate,direct-import`,
          currentUrl: location.href
        });
        return;
      }
      const fillResult = await attemptPromptFill(command, request);
      if (!fillResult?.ok || !request.autoGenerate) return;
      await new Promise((resolve) => setTimeout(resolve, 450));
      const generateResult = await clickGenerate();
      await report(command, {
        eventType: "autostart-generate",
        status: generateResult?.ok ? "clicked" : "failed",
        detail: generateResult?.label || generateResult?.error || "generate attempted",
        currentUrl: generateResult?.currentUrl || location.href
      });
    } catch (error) {
      await report(command, {
        eventType: "autostart",
        status: "failed",
        detail: String(error && error.message ? error.message : error),
        currentUrl: location.href
      });
      console.warn("Video Studio Grok autostart failed", error);
    }
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    (async () => {
      if (message?.type === "fill-prompt") {
        sendResponse(await fillPrompt(message.command || {}));
        return;
      }
      if (message?.type === "click-generate") {
        sendResponse(await clickGenerate());
        return;
      }
      if (message?.type === "click-download") {
        sendResponse(await clickDownload(message.command || {}));
        return;
      }
      if (message?.type === "probe") {
        const mode = activeVideoModeControl();
        sendResponse({
          ok: true,
          provider: "grok-web-video",
          capabilities: providerCapabilities({ provider: "grok-web-video" }),
          currentUrl: location.href,
          editableCount: editableCandidates().length,
          videoCandidates: collectVideoCandidates(),
          activeVideoMode: Boolean(mode),
          activeVideoModeLabel: mode ? textOf(mode) : ""
        });
        return;
      }
      sendResponse({ ok: false, error: "unknown message" });
    })();
    return true;
  });

  markCompanionLoaded();
  announceContentReady();
  setTimeout(runAutostart, 800);
})();
